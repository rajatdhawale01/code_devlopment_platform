from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from functools import wraps
import subprocess
import sys
import os
import tempfile
import shutil

app = Flask(__name__)
app.secret_key = "change-this-secret-key-for-production"

# -------------------------------------------------------------------
# DEMO USERS (login + management)
# -------------------------------------------------------------------
USERS = {
    "admin1": {"password": "admin123", "role": "admin"},
    "editor1": {"password": "editor123", "role": "editor"},
    "viewer1": {"password": "viewer123", "role": "viewer"},
}

# -------------------------------------------------------------------
# DEMO PROBLEMS (for editor/viewer)
# -------------------------------------------------------------------
PROBLEMS = [
    {
        "id": 1,
        "title": "Sum of Two Numbers",
        "difficulty": "Easy",
        "tags": "math, basics",
        "statement": "Given two integers a and b, print their sum.",
    },
    {
        "id": 2,
        "title": "Reverse a String",
        "difficulty": "Easy",
        "tags": "string",
        "statement": "Given a string s, print the reversed string.",
    },
]
NEXT_PROBLEM_ID = 3


# -------------------------------------------------------------------
# Helpers: auth / roles
# -------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "username" not in session:
                return redirect(url_for("login"))
            user_role = session.get("role")
            if user_role not in roles:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# -------------------------------------------------------------------
# Login / Logout
# -------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        user = USERS.get(username)
        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------------------------
# Dashboard (overview page)
# -------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    role = session.get("role")

    total_users = len(USERS)
    total_problems = len(PROBLEMS)

    difficulties = {}
    for p in PROBLEMS:
        difficulties[p["difficulty"]] = difficulties.get(p["difficulty"], 0) + 1

    return render_template(
        "dashboard.html",
        username=session.get("username"),
        role=role,
        total_users=total_users,
        total_problems=total_problems,
        difficulties=difficulties,
    )


# -------------------------------------------------------------------
# USER MANAGEMENT (Admin)
# -------------------------------------------------------------------
@app.route("/admin", methods=["GET", "POST"])
@roles_required("admin")
def admin_page():
    """
    Admin can:
      - view all users
      - add a new user
      - delete a user
      - change a user's role
    """
    global USERS

    if request.method == "POST":
        action = request.form.get("action")

        # ADD USER
        if action == "add":
            new_username = (request.form.get("username") or "").strip()
            new_password = (request.form.get("password") or "").strip()
            new_role = (request.form.get("role") or "").strip()

            if not new_username or not new_password or not new_role:
                flash("All fields are required to add a user.", "error")
            elif new_username in USERS:
                flash("User already exists.", "error")
            elif new_role not in ("admin", "editor", "viewer"):
                flash("Role must be admin / editor / viewer.", "error")
            else:
                USERS[new_username] = {"password": new_password, "role": new_role}
                flash(f"User '{new_username}' added successfully.", "success")

        # DELETE USER
        elif action == "delete":
            target = (request.form.get("username_to_delete") or "").strip()
            if target == session.get("username"):
                flash("You cannot delete yourself.", "error")
            elif target not in USERS:
                flash("User does not exist.", "error")
            else:
                USERS.pop(target)
                flash(f"User '{target}' deleted.", "success")

        # UPDATE ROLE
        elif action == "update_role":
            target = (request.form.get("username_to_update") or "").strip()
            new_role = (request.form.get("new_role") or "").strip()
            if target not in USERS:
                flash("User does not exist.", "error")
            elif new_role not in ("admin", "editor", "viewer"):
                flash("Role must be admin / editor / viewer.", "error")
            else:
                USERS[target]["role"] = new_role
                # If admin changed their own role, update session as well
                if target == session.get("username"):
                    session["role"] = new_role
                flash(f"Updated role for '{target}' to {new_role}.", "success")

        return redirect(url_for("admin_page"))

    # GET – show table
    users_list = [
        {"username": u, "role": info["role"]}
        for u, info in USERS.items()
    ]

    return render_template(
        "admin.html",
        username=session.get("username"),
        role=session.get("role"),
        users=users_list,
    )


# -------------------------------------------------------------------
# EDITOR – manage problem bank
# -------------------------------------------------------------------
@app.route("/editor", methods=["GET", "POST"])
@roles_required("admin", "editor")
def editor_page():
    """
    Problem Bank:
      - GET  /editor           -> show list + add/edit form
      - GET  /editor?edit_id=X -> show list + form prefilled for problem X
      - POST action=add        -> add problem
      - POST action=delete     -> delete problem
      - POST action=update     -> update existing problem
    """
    global PROBLEMS, NEXT_PROBLEM_ID

    if request.method == "POST":
        action = request.form.get("action")

        # ------- ADD -------
        if action == "add":
            title = (request.form.get("title") or "").strip()
            difficulty = (request.form.get("difficulty") or "").strip()
            tags = (request.form.get("tags") or "").strip()
            statement = (request.form.get("statement") or "").strip()

            if not title or not difficulty:
                flash("Title and difficulty are required.", "error")
            else:
                PROBLEMS.append(
                    {
                        "id": NEXT_PROBLEM_ID,
                        "title": title,
                        "difficulty": difficulty,
                        "tags": tags,
                        "statement": statement,
                    }
                )
                NEXT_PROBLEM_ID += 1
                flash("Problem added.", "success")

        # ------- DELETE -------
        elif action == "delete":
            pid = request.form.get("problem_id")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

            if pid is None:
                flash("Invalid problem ID.", "error")
            else:
                before = len(PROBLEMS)
                PROBLEMS = [p for p in PROBLEMS if p["id"] != pid]
                if len(PROBLEMS) < before:
                    flash(f"Problem {pid} deleted.", "success")
                else:
                    flash("Problem not found.", "error")

        # ------- UPDATE -------
        elif action == "update":
            pid = request.form.get("problem_id")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None

            if pid is None:
                flash("Invalid problem ID for update.", "error")
            else:
                problem = next((p for p in PROBLEMS if p["id"] == pid), None)
                if not problem:
                    flash("Problem not found.", "error")
                else:
                    title = (request.form.get("title") or "").strip()
                    difficulty = (request.form.get("difficulty") or "").strip()
                    tags = (request.form.get("tags") or "").strip()
                    statement = (request.form.get("statement") or "").strip()

                    if not title or not difficulty:
                        flash("Title and difficulty are required.", "error")
                    else:
                        problem["title"] = title
                        problem["difficulty"] = difficulty
                        problem["tags"] = tags
                        problem["statement"] = statement
                        flash(f"Problem {pid} updated.", "success")

        # after any POST, reload clean page (no edit_id in URL)
        return redirect(url_for("editor_page"))

    # ------- GET -------
    edit_id = request.args.get("edit_id", type=int)
    edit_problem = None
    if edit_id:
        edit_problem = next((p for p in PROBLEMS if p["id"] == edit_id), None)

    return render_template(
        "editor.html",
        username=session.get("username"),
        role=session.get("role"),
        problems=PROBLEMS,
        edit_problem=edit_problem,  # problem currently being edited (or None)
    )



# -------------------------------------------------------------------
# VIEWER – see problem list
# -------------------------------------------------------------------
@app.route("/viewer")
@roles_required("admin", "editor", "viewer")
def viewer_page():
    return render_template(
        "viewer.html",
        username=session.get("username"),
        role=session.get("role"),
        problems=PROBLEMS,
    )


@app.route("/problem/<int:pid>")
@login_required
def problem_detail(pid):
    problem = next((p for p in PROBLEMS if p["id"] == pid), None)
    if not problem:
        return "Problem not found", 404

    return render_template(
        "problem_detail.html",
        username=session.get("username"),
        role=session.get("role"),
        problem=problem,
    )


# -------------------------------------------------------------------
# CODE RUNNER PAGE
# -------------------------------------------------------------------
@app.route("/code")
@login_required
def code_page():
    return render_template(
        "code_runner.html",
        username=session.get("username"),
        role=session.get("role"),
    )


# -------------------------------------------------------------------
# CODE RUNNER API – multi-language
# -------------------------------------------------------------------
@app.route("/run-code", methods=["POST"])
@login_required
def run_code():
    """
    Multi-language code runner for local use:
      - Python: uses current interpreter
      - JavaScript: node -e
      - C++: g++ compile then run binary
      - Java: javac Main.java then java Main
    """
    try:
        data = request.get_json(silent=True) or {}
        language = data.get("language", "python")
        source_code = data.get("source_code") or ""

        def format_result(proc: subprocess.CompletedProcess) -> str:
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            if not stdout and not stderr:
                return "[No output produced]"
            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append("\n[Errors]\n" + stderr)
            return "".join(parts)

        # -------- PYTHON --------
        if language == "python":
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", source_code],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return jsonify({"output": format_result(proc)})
            except subprocess.TimeoutExpired:
                return jsonify({"output": "Error: Python code execution timed out."})
            except Exception as e:
                app.logger.exception("Python execution error")
                return jsonify({"output": f"Unexpected Python error: {e}"})

        # -------- JAVASCRIPT (Node.js) --------
        if language == "javascript":
            try:
                proc = subprocess.run(
                    ["node", "-e", source_code],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return jsonify({"output": format_result(proc)})
            except FileNotFoundError:
                return jsonify({
                    "output": "Error: 'node' not found. Please install Node.js to run JavaScript code."
                })
            except subprocess.TimeoutExpired:
                return jsonify({"output": "Error: JavaScript code execution timed out."})
            except Exception as e:
                app.logger.exception("JavaScript execution error")
                return jsonify({"output": f"Unexpected JavaScript error: {e}"})

        # -------- C++ (g++) --------
        if language == "cpp":
            tmp_dir = tempfile.mkdtemp(prefix="coderunner_cpp_")
            src_path = os.path.join(tmp_dir, "main.cpp")
            exe_path = os.path.join(tmp_dir, "a.out")

            try:
                with open(src_path, "w", encoding="utf-8") as f:
                    f.write(source_code)

                try:
                    compile_proc = subprocess.run(
                        ["g++", src_path, "-o", exe_path],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except FileNotFoundError:
                    return jsonify({
                        "output": "Error: 'g++' not found. Please install a C++ compiler (g++)."
                    })

                if compile_proc.returncode != 0:
                    return jsonify({
                        "output": "[Compilation Error]\n" + (compile_proc.stderr or "").strip()
                    })

                try:
                    run_proc = subprocess.run(
                        [exe_path],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    return jsonify({"output": format_result(run_proc)})
                except subprocess.TimeoutExpired:
                    return jsonify({"output": "Error: C++ program execution timed out."})
            except Exception as e:
                app.logger.exception("C++ execution error")
                return jsonify({"output": f"Unexpected C++ error: {e}"})
            finally:
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

        # -------- JAVA (javac + java Main) --------
        if language == "java":
            tmp_dir = tempfile.mkdtemp(prefix="coderunner_java_")
            src_path = os.path.join(tmp_dir, "Main.java")

            try:
                with open(src_path, "w", encoding="utf-8") as f:
                    f.write(source_code)

                try:
                    compile_proc = subprocess.run(
                        ["javac", "Main.java"],
                        cwd=tmp_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except FileNotFoundError:
                    return jsonify({
                        "output": "Error: 'javac' not found. Please install Java JDK to run Java code."
                    })

                if compile_proc.returncode != 0:
                    return jsonify({
                        "output": "[Compilation Error]\n" + (compile_proc.stderr or "").strip()
                    })

                try:
                    run_proc = subprocess.run(
                        ["java", "Main"],
                        cwd=tmp_dir,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    return jsonify({"output": format_result(run_proc)})
                except FileNotFoundError:
                    return jsonify({
                        "output": "Error: 'java' runtime not found. Please install Java JDK/JRE."
                    })
                except subprocess.TimeoutExpired:
                    return jsonify({"output": "Error: Java program execution timed out."})
            except Exception as e:
                app.logger.exception("Java execution error")
                return jsonify({"output": f"Unexpected Java error: {e}"})
            finally:
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

        return jsonify({
            "output": f"Language '{language}' is not supported yet."
        })

    except Exception as outer_e:
        app.logger.exception("Top-level error in /run-code")
        return (
            jsonify({
                "output": f"Server error in /run-code: {type(outer_e).__name__}: {outer_e}"
            }),
            500,
        )


# -------------------------------------------------------------------
# Errors + main
# -------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return "404 - Page not found", 404


@app.errorhandler(500)
def internal_error(e):
    return "500 - Internal server error (check Flask logs).", 500


if __name__ == "__main__":
    app.run(debug=True)

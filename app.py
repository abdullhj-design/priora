# rebuild trigger
from flask import Flask, jsonify, request, session, render_template
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from google import genai
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz

app = Flask(__name__)
app.secret_key = 'my-secret-key-2026'
CORS(app, supports_credentials=True)
app.config['JSON_AS_ASCII'] = False
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get('MYSQLHOST', 'localhost'),
        user=os.environ.get('MYSQLUSER', 'root'),
        password=os.environ.get('MYSQLPASSWORD', '0000'),
        database=os.environ.get('MYSQLDATABASE', 'sahb_taskes'),
        port=os.environ.get('MYSQLPORT', 3306)
    )
    

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login-page')
def login_page():
    return render_template('login.html')

@app.route('/app-page')
def app_page():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('index.html', username=session['username'])

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data['username']
    password = data['password']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    existing_user = cursor.fetchone()

    if existing_user:
        cursor.close()
        conn.close()
        return jsonify({"error": "اسم المستخدم موجود مسبقًا"}), 400

    hashed_password = generate_password_hash(password)
    cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
    conn.commit()

    cursor.close()
    conn.close()
    return jsonify({"message": "تم إنشاء الحساب بنجاح"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']
    password = data['password']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({"message": "تم تسجيل الدخول بنجاح", "username": user['username']}), 200

    return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "تم تسجيل الخروج"}), 200

@app.route('/tasks', methods=['GET'])
def get_tasks():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM tasks WHERE user_id = %s", (session['user_id'],))
    user_tasks = cursor.fetchall()

    cursor.close()
    conn.close()
    return jsonify(user_tasks)

@app.route('/tasks', methods=['POST'])
def add_task():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    data = request.get_json()
    title = data['title']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO tasks (title, done, user_id) VALUES (%s, %s, %s)",
                   (title, False, session['user_id']))
    conn.commit()

    new_task_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return jsonify({"id": new_task_id, "title": title, "done": False}), 201

@app.route('/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()

    cursor.close()
    conn.close()
    return jsonify({"message": "تم الحذف"}), 200

@app.route('/tasks/<int:task_id>/toggle', methods=['PUT'])
def toggle_task(task_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT done FROM tasks WHERE id = %s", (task_id,))
    task = cursor.fetchone()

    new_status = not task['done']
    cursor.execute("UPDATE tasks SET done = %s WHERE id = %s", (new_status, task_id))
    conn.commit()

    cursor.close()
    conn.close()
    return jsonify({"id": task_id, "done": new_status}), 200

@app.route('/tasks/<int:task_id>/analyze', methods=['GET'])
def analyze_task(task_id):
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT title FROM tasks WHERE id = %s", (task_id,))
    task = cursor.fetchone()
    cursor.close()
    conn.close()

    if not task:
        return jsonify({"error": "المهمة غير موجودة"}), 404

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=f"هذي مهمة: \"{task['title']}\". اكتب لي أولاً ملخص قصير جداً لها (سطر واحد)، وبعدها اقترح 3 إلى 5 خطوات عملية لتنفيذها. رد فقط بصيغة JSON بهذا الشكل بالضبط، بدون أي كلام إضافي قبله أو بعده: {{\"summary\": \"...\", \"steps\": [\"...\", \"...\"]}}"
        )

        raw_text = response.text.strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(raw_text)

        return jsonify(parsed), 200

    except Exception as e:
        print("=== خطأ بالذكاء الاصطناعي ===")
        print(str(e))
        print("==========================")
        return jsonify({"error": str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    data = request.get_json()
    user_message = data['message']

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            config={"system_instruction": "أنت مساعد ذكي داخل تطبيق إدارة مهام اسمه Priora. إذا سألك أحد من طوّر هذا التطبيق أو من صممه، أجب بأن المطور هو عبدالله علي الحربي."},
            contents=user_message
        )

        reply = response.text
        return jsonify({"reply": reply}), 200

    except Exception as e:
        print("=== خطأ بالشات بوت ===")
        print(str(e))
        print("==========================")
        return jsonify({"error": str(e)}), 500

@app.route('/admin')
def admin_page():
    if 'user_id' not in session:
        return render_template('login.html')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or not user['is_admin']:
        return "غير مصرح لك بالدخول لهذي الصفحة", 403

    return render_template('admin.html')

@app.route('/admin/users', methods=['GET'])
def admin_get_users():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session['user_id'],))
    current_user = cursor.fetchone()

    if not current_user or not current_user['is_admin']:
        cursor.close()
        conn.close()
        return jsonify({"error": "غير مصرح"}), 403

    cursor.execute("SELECT id, username, is_admin FROM users")
    all_users = cursor.fetchall()

    cursor.execute("""
        SELECT tasks.id, tasks.title, tasks.done, users.username
        FROM tasks
        JOIN users ON tasks.user_id = users.id
    """)
    all_tasks = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify({"users": all_users, "tasks": all_tasks})

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session['user_id'],))
    current_user = cursor.fetchone()

    if not current_user or not current_user['is_admin']:
        cursor.close()
        conn.close()
        return jsonify({"error": "غير مصرح"}), 403

    cursor.execute("DELETE FROM tasks WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"message": "تم حذف المستخدم"}), 200
@app.route('/tasks/prioritize', methods=['GET'])
def prioritize_tasks():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, title FROM tasks WHERE user_id = %s AND done = 0", (session['user_id'],))
    tasks = cursor.fetchall()
    cursor.close()
    conn.close()

    if not tasks:
        return jsonify({"message": "لا توجد مهام غير مكتملة لترتيبها"}), 200

    tasks_list = "\n".join([f"- {t['title']}" for t in tasks])

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=f"هذي قائمة مهام المستخدم اليوم:\n{tasks_list}\n\nرتّبها من الأهم للأقل أهمية، وحدد أي مهمة يبدأ بها أولاً مع سبب قصير. رد فقط بصيغة JSON بهذا الشكل بالضبط، بدون أي كلام إضافي: {{\"start_with\": \"...\", \"reason\": \"...\", \"ordered\": [\"...\", \"...\"]}}"
        )

        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(raw_text)
        return jsonify(parsed), 200

    except Exception as e:
        print("=== خطأ بترتيب المهام ===")
        print(str(e))
        return jsonify({"error": str(e)}), 500
        
def delete_completed_tasks():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE done = 1")
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[{datetime.now()}] تم حذف المهام المكتملة تلقائيًا")
    except Exception as e:
        print(f"[{datetime.now()}] خطأ بحذف المهام: {str(e)}")

scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Riyadh'))
scheduler.add_job(delete_completed_tasks, 'cron', hour=2, minute=0)
scheduler.start()


if __name__ == '__main__':
    app.run(debug=True)
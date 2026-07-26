import os
import uuid
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_from_directory
)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import models

app = Flask(__name__)
app.secret_key = 'expense-system-secret-key-2024'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Login Manager ──

class User:
    def __init__(self, row):
        self.id = row['id']
        self.username = row['username']
        self.full_name = row['full_name']
        self.role = row['role']
        self.is_authenticated = True

    def get_id(self):
        return str(self.id)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                flash('ليس لديك صلاحية للوصول لهذه الصفحة', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Auth Routes ──

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = models.get_user_by_username(username)
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            flash(f'مرحباً {user["full_name"]}', 'success')
            return redirect(url_for('dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('تم تسجيل الخروج', 'success')
    return redirect(url_for('login'))


# ── Dashboard ──

@app.route('/')
@login_required
def dashboard():
    stats = models.get_dashboard_stats()
    role = session.get('role')

    pending_fm = []
    pending_gm = []
    pending_payment = []
    my_expenses = []

    if role in ('accountant', 'admin'):
        my_expenses = models.get_expenses()
    if role in ('finance_manager', 'admin'):
        pending_fm = models.get_expenses(status='pending_fm')
        pending_payment = models.get_pending_payment()
    if role in ('general_manager', 'admin'):
        pending_gm = models.get_expenses(status='pending_gm')

    return render_template('dashboard.html',
                           stats=stats, role=role,
                           pending_fm=len(pending_fm),
                           pending_gm=len(pending_gm),
                           pending_payment=len(pending_payment),
                           my_expenses=my_expenses)


# ── Accountant: Add Expense ──

@app.route('/expense/add', methods=['GET', 'POST'])
@login_required
@role_required('accountant', 'admin')
def add_expense():
    branches = models.get_branches()
    types = models.get_expense_types()

    if request.method == 'POST':
        data = {
            'date': request.form['date'],
            'branch': request.form['branch'],
            'expense_type': request.form['expense_type'],
            'description': request.form['description'],
            'amount': request.form['amount'],
            'payment_method': request.form.get('payment_method', 'نقدي'),
            'notes': request.form.get('notes', ''),
        }

        filename = ''
        original_name = ''
        if 'invoice' in request.files:
            file = request.files['invoice']
            if file and file.filename and allowed_file(file.filename):
                original_name = secure_filename(file.filename)
                ext = original_name.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        ref = models.create_expense(data, session['user_id'], filename, original_name)
        flash(f'تم حفظ المصروف بنجاح - رقم: {ref}', 'success')
        return redirect(url_for('my_expenses'))

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('add_expense.html', branches=branches, types=types, today=today)


@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ── My Expenses ──

@app.route('/my-expenses')
@login_required
@role_required('accountant', 'admin')
def my_expenses():
    expenses = models.get_expenses()
    return render_template('my_expenses.html', expenses=expenses)


@app.route('/expense/delete/<ref>', methods=['POST'])
@login_required
@role_required('accountant', 'admin')
def delete_expense(ref):
    exp = models.get_expense_by_ref(ref)
    if exp and exp['status'] == 'pending_fm':
        # Delete invoice file if exists
        if exp['invoice_filename']:
            path = os.path.join(app.config['UPLOAD_FOLDER'], exp['invoice_filename'])
            if os.path.exists(path):
                os.remove(path)
        models.delete_expense(ref)
        flash('تم حذف المصروف', 'success')
    else:
        flash('لا يمكن حذف هذا المصروف', 'error')
    return redirect(url_for('my_expenses'))


# ── Financial Manager ──

@app.route('/fm/review')
@login_required
@role_required('finance_manager', 'admin')
def fm_review():
    expenses = models.get_expenses(status='pending_fm')
    return render_template('fm_review.html', expenses=expenses)


@app.route('/fm/approve/<ref>', methods=['POST'])
@login_required
@role_required('finance_manager', 'admin')
def fm_approve(ref):
    notes = request.form.get('notes', '')
    models.fm_approve(ref, notes)
    flash(f'تم الموافقة المبدئية على المصروف {ref}', 'success')
    return redirect(url_for('fm_review'))


@app.route('/fm/reject/<ref>', methods=['POST'])
@login_required
@role_required('finance_manager', 'admin')
def fm_reject(ref):
    reason = request.form.get('reason', '')
    models.fm_reject(ref, reason)
    flash(f'تم رفض المصروف {ref} من المدير المالي', 'error')
    return redirect(url_for('fm_review'))


@app.route('/fm/all')
@login_required
@role_required('finance_manager', 'admin')
def fm_all():
    expenses = models.get_expenses()
    return render_template('fm_all.html', expenses=expenses)


# ── General Manager ──

@app.route('/gm/review')
@login_required
@role_required('general_manager', 'admin')
def gm_review():
    expenses = models.get_expenses(status='pending_gm')
    return render_template('gm_review.html', expenses=expenses)


@app.route('/gm/approve/<ref>', methods=['POST'])
@login_required
@role_required('general_manager', 'admin')
def gm_approve(ref):
    notes = request.form.get('notes', '')
    models.gm_approve(ref, notes)
    flash(f'تم التصديق النهائي على المصروف {ref}', 'success')
    return redirect(url_for('gm_review'))


@app.route('/gm/reject/<ref>', methods=['POST'])
@login_required
@role_required('general_manager', 'admin')
def gm_reject(ref):
    reason = request.form.get('reason', '')
    models.gm_reject(ref, reason)
    flash(f'تم رفض المصروف {ref} نهائياً من المدير العام', 'error')
    return redirect(url_for('gm_review'))


@app.route('/gm/all')
@login_required
@role_required('general_manager', 'admin')
def gm_all():
    expenses = models.get_expenses()
    return render_template('gm_all.html', expenses=expenses)


# ── Payment / Transfer (Finance Manager) ──

@app.route('/fm/payment')
@login_required
@role_required('finance_manager', 'admin')
def fm_payment():
    expenses = models.get_pending_payment()
    return render_template('fm_payment.html', expenses=expenses)


@app.route('/fm/pay/<ref>', methods=['POST'])
@login_required
@role_required('finance_manager', 'admin')
def fm_pay(ref):
    payment_method_used = request.form['payment_method_used']
    payment_reference = request.form.get('payment_reference', '')
    paid_notes = request.form.get('paid_notes', '')
    models.pay_expense(ref, payment_method_used, payment_reference, paid_notes, session['user_id'])
    flash(f'تم تسجيل التحويل/الصرف للمصروف {ref}', 'success')
    return redirect(url_for('fm_payment'))


@app.route('/fm/paid')
@login_required
@role_required('finance_manager', 'admin')
def fm_paid():
    expenses = models.get_expenses(status='paid')
    total = sum(r['amount'] for r in expenses)
    return render_template('fm_paid.html', expenses=expenses, total=total)


# ── Reports ──

@app.route('/reports')
@login_required
def reports():
    branches = models.get_branches()
    types = models.get_expense_types()
    status = request.args.get('status', '')
    branch = request.args.get('branch', '')
    exp_type = request.args.get('expense_type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    expenses = models.get_expenses(
        status=status or None,
        branch=branch or None,
        exp_type=exp_type or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    total = sum(r['amount'] for r in expenses)

    return render_template('reports.html',
                           expenses=expenses, total=total,
                           branches=branches, types=types,
                           filters={'status': status, 'branch': branch,
                                    'expense_type': exp_type,
                                    'date_from': date_from, 'date_to': date_to})


# ── Admin: Users ──

@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    users = models.get_all_users()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_user():
    username = request.form['username'].strip()
    password = request.form['password']
    full_name = request.form['full_name'].strip()
    role = request.form['role']
    ok, msg = models.create_user(username, password, full_name, role)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/toggle/<int:uid>', methods=['POST'])
@login_required
@role_required('admin')
def admin_toggle_user(uid):
    models.toggle_user(uid)
    flash('تم تحديث حالة المستخدم', 'success')
    return redirect(url_for('admin_users'))


# ── Admin: Manage Types & Branches ──

@app.route('/admin/types', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_types():
    if request.method == 'POST':
        name = request.form['name'].strip()
        desc = request.form.get('description', '')
        if name:
            if models.add_expense_type(name, desc):
                flash('تمت إضافة النوع', 'success')
            else:
                flash('هذا النوع موجود بالفعل', 'error')
    types = models.get_expense_types()
    return render_template('admin_types.html', types=types)


@app.route('/admin/types/delete/<int:tid>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_type(tid):
    models.remove_expense_type(tid)
    flash('تم حذف النوع', 'success')
    return redirect(url_for('admin_types'))


@app.route('/admin/branches', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_branches():
    if request.method == 'POST':
        name = request.form['name'].strip()
        address = request.form.get('address', '')
        if name:
            if models.add_branch(name, address):
                flash('تمت إضافة الفرع', 'success')
            else:
                flash('هذا الفرع موجود بالفعل', 'error')
    branches = models.get_branches()
    return render_template('admin_branches.html', branches=branches)


@app.route('/admin/branches/delete/<int:bid>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_branch(bid):
    models.remove_branch(bid)
    flash('تم حذف الفرع', 'success')
    return redirect(url_for('admin_branches'))


# ── Init & Run ──

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
models.init_db()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)

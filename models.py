import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'expense.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('accountant','finance_manager','general_manager','admin')),
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS expense_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            address TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number TEXT UNIQUE NOT NULL,
            date TEXT NOT NULL,
            branch TEXT NOT NULL,
            expense_type TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            invoice_filename TEXT DEFAULT '',
            invoice_original_name TEXT DEFAULT '',
            payment_method TEXT DEFAULT 'نقدي',
            notes TEXT DEFAULT '',
            requester_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_fm',
            fm_review_date TEXT DEFAULT '',
            fm_notes TEXT DEFAULT '',
            fm_decision TEXT DEFAULT '',
            gm_review_date TEXT DEFAULT '',
            gm_notes TEXT DEFAULT '',
            gm_decision TEXT DEFAULT '',
            payment_date TEXT DEFAULT '',
            payment_method_used TEXT DEFAULT '',
            payment_reference TEXT DEFAULT '',
            paid_by INTEGER DEFAULT NULL,
            paid_notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (requester_id) REFERENCES users(id),
            FOREIGN KEY (paid_by) REFERENCES users(id)
        );
    ''')

    # ── Migration: add payment columns if missing ──
    cur = conn.cursor()
    existing = {row[1] for row in cur.execute("PRAGMA table_info(expenses)").fetchall()}
    cols_to_add = [
        ('payment_date', "TEXT DEFAULT ''"),
        ('payment_method_used', "TEXT DEFAULT ''"),
        ('payment_reference', "TEXT DEFAULT ''"),
        ('paid_by', 'INTEGER DEFAULT NULL'),
        ('paid_notes', "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in cols_to_add:
        if col_name not in existing:
            cur.execute(f'ALTER TABLE expenses ADD COLUMN {col_name} {col_def}')

    # Migrate old 'approved' to 'pending_payment' so payment flow starts fresh
    cur.execute("UPDATE expenses SET status='pending_payment' WHERE status='approved'")

    cur = conn.cursor()

    # Default expense types
    types = [
        ('رواتب وأجور', 'مرتبات وعمولات'),
        ('إيجارات', 'إيجار مكاتب وعقارات'),
        ('مشتريات', 'مشتريات متنوعة'),
        ('فواتير خدمات', 'كهرباء، مياه، هاتف، إنترنت'),
        ('صيانة', 'صيانة معدات ومباني'),
        ('سفر وتنقلات', 'مصاريف سفر ونقل'),
        ('مصاريف إدارية', 'مكتبية وإدارية'),
        ('أخرى', 'أخرى'),
    ]
    for name, desc in types:
        try:
            cur.execute('INSERT OR IGNORE INTO expense_types (name, description) VALUES (?,?)', (name, desc))
        except sqlite3.IntegrityError:
            pass

    # Default branches
    branches = [
        'الفرع الرئيسي', 'فرع بورتسودان', 'فرع كسلا', 'فرع كوستي',
        'فرع الأبيض', 'فرع عطبرة', 'فرع الخرطوم', 'فرع مدني', 'فرع سنار'
    ]
    for b in branches:
        try:
            cur.execute('INSERT OR IGNORE INTO branches (name) VALUES (?)', (b,))
        except sqlite3.IntegrityError:
            pass

    # Default admin user
    admin_hash = generate_password_hash('admin123')
    try:
        cur.execute(
            'INSERT OR IGNORE INTO users (username, password, full_name, role) VALUES (?,?,?,?)',
            ('admin', admin_hash, 'مدير النظام', 'admin')
        )
    except sqlite3.IntegrityError:
        pass

    # Default users for each role
    users = [
        ('accountant', 'acc123', 'أحمد المحاسب', 'accountant'),
        ('fm_manager', 'fm123', 'محمد المدير المالي', 'finance_manager'),
        ('gm_manager', 'gm123', 'خالد المدير العام', 'general_manager'),
    ]
    for uname, pwd, fname, role in users:
        pwd_hash = generate_password_hash(pwd)
        try:
            cur.execute(
                'INSERT OR IGNORE INTO users (username, password, full_name, role) VALUES (?,?,?,?)',
                (uname, pwd_hash, fname, role)
            )
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()


# ── User helpers ──

def get_user_by_username(username):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND active = 1', (username,)).fetchone()
    conn.close()
    return user


def get_user_by_id(uid):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    conn.close()
    return user


def get_all_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY role, full_name').fetchall()
    conn.close()
    return users


def create_user(username, password, full_name, role):
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username, password, full_name, role) VALUES (?,?,?,?)',
            (username, generate_password_hash(password), full_name, role)
        )
        conn.commit()
        return True, 'تم إنشاء المستخدم بنجاح'
    except sqlite3.IntegrityError:
        return False, 'اسم المستخدم موجود بالفعل'
    finally:
        conn.close()


def toggle_user(uid):
    conn = get_db()
    user = conn.execute('SELECT active FROM users WHERE id = ?', (uid,)).fetchone()
    if user:
        new_status = 0 if user['active'] else 1
        conn.execute('UPDATE users SET active = ? WHERE id = ?', (new_status, uid))
        conn.commit()
    conn.close()


# ── Expense helpers ──

def generate_ref_number():
    conn = get_db()
    cur = conn.execute("SELECT COUNT(*) as cnt FROM expenses")
    count = cur.fetchone()['cnt'] + 1
    year = datetime.now().strftime('%y')
    conn.close()
    return f'EXP-{year}-{count:04d}'


def create_expense(data, user_id, filename='', original_name=''):
    conn = get_db()
    ref = generate_ref_number()
    conn.execute('''INSERT INTO expenses
        (ref_number, date, branch, expense_type, description, amount,
         invoice_filename, invoice_original_name, payment_method, notes,
         requester_id, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ref, data['date'], data['branch'], data['expense_type'],
         data['description'], float(data['amount']),
         filename, original_name,
         data.get('payment_method', 'نقدي'), data.get('notes', ''),
         user_id, 'pending_fm'))
    conn.commit()
    conn.close()
    return ref


def get_expenses(status=None, branch=None, exp_type=None, date_from=None, date_to=None):
    conn = get_db()
    query = '''SELECT e.*, u.full_name as requester_name
               FROM expenses e JOIN users u ON e.requester_id = u.id WHERE 1=1'''
    params = []
    if status:
        query += ' AND e.status = ?'
        params.append(status)
    if branch:
        query += ' AND e.branch = ?'
        params.append(branch)
    if exp_type:
        query += ' AND e.expense_type = ?'
        params.append(exp_type)
    if date_from:
        query += ' AND e.date >= ?'
        params.append(date_from)
    if date_to:
        query += ' AND e.date <= ?'
        params.append(date_to)
    query += ' ORDER BY e.created_at DESC'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_expense_by_ref(ref):
    conn = get_db()
    row = conn.execute('''SELECT e.*, u.full_name as requester_name
                          FROM expenses e JOIN users u ON e.requester_id = u.id
                          WHERE e.ref_number = ?''', (ref,)).fetchone()
    conn.close()
    return row


def fm_approve(ref, notes=''):
    conn = get_db()
    conn.execute('''UPDATE expenses SET status='pending_gm',
        fm_review_date=?, fm_notes=?, fm_decision='تم التصديق المبدئي'
        WHERE ref_number=?''',
        (datetime.now().isoformat(), notes, ref))
    conn.commit()
    conn.close()


def fm_reject(ref, reason=''):
    conn = get_db()
    conn.execute('''UPDATE expenses SET status='fm_rejected',
        fm_review_date=?, fm_notes=?, fm_decision='مرفوض من المدير المالي'
        WHERE ref_number=?''',
        (datetime.now().isoformat(), reason, ref))
    conn.commit()
    conn.close()


def gm_approve(ref, notes=''):
    conn = get_db()
    conn.execute('''UPDATE expenses SET status='pending_payment',
        gm_review_date=?, gm_notes=?, gm_decision='تم التصديق نهائياً'
        WHERE ref_number=?''',
        (datetime.now().isoformat(), notes, ref))
    conn.commit()
    conn.close()


def gm_reject(ref, reason=''):
    conn = get_db()
    conn.execute('''UPDATE expenses SET status='gm_rejected',
        gm_review_date=?, gm_notes=?, gm_decision='مرفوض من المدير العام'
        WHERE ref_number=?''',
        (datetime.now().isoformat(), reason, ref))
    conn.commit()
    conn.close()


# ── Payment / Transfer ──

def pay_expense(ref, payment_method_used, payment_reference, paid_notes, paid_by_user_id):
    conn = get_db()
    conn.execute('''UPDATE expenses SET
        status='paid',
        payment_date=?,
        payment_method_used=?,
        payment_reference=?,
        paid_by=?,
        paid_notes=?
        WHERE ref_number=?''',
        (datetime.now().isoformat(), payment_method_used,
         payment_reference, paid_by_user_id, paid_notes, ref))
    conn.commit()
    conn.close()


def get_pending_payment():
    conn = get_db()
    rows = conn.execute('''SELECT e.*, u.full_name as requester_name
        FROM expenses e JOIN users u ON e.requester_id = u.id
        WHERE e.status='pending_payment'
        ORDER BY e.gm_review_date DESC''').fetchall()
    conn.close()
    return rows


def delete_expense(ref):
    conn = get_db()
    conn.execute('DELETE FROM expenses WHERE ref_number = ?', (ref,))
    conn.commit()
    conn.close()


# ── Type & Branch helpers ──

def get_expense_types():
    conn = get_db()
    rows = conn.execute('SELECT * FROM expense_types ORDER BY id').fetchall()
    conn.close()
    return rows


def get_branches():
    conn = get_db()
    rows = conn.execute('SELECT * FROM branches ORDER BY id').fetchall()
    conn.close()
    return rows


def add_expense_type(name, desc=''):
    conn = get_db()
    try:
        conn.execute('INSERT INTO expense_types (name, description) VALUES (?,?)', (name, desc))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def add_branch(name, address=''):
    conn = get_db()
    try:
        conn.execute('INSERT INTO branches (name, address) VALUES (?,?)', (name, address))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_expense_type(tid):
    conn = get_db()
    conn.execute('DELETE FROM expense_types WHERE id = ?', (tid,))
    conn.commit()
    conn.close()


def remove_branch(bid):
    conn = get_db()
    conn.execute('DELETE FROM branches WHERE id = ?', (bid,))
    conn.commit()
    conn.close()


# ── Dashboard stats ──

def get_dashboard_stats():
    conn = get_db()
    all_rows = conn.execute('SELECT * FROM expenses').fetchall()

    total = sum(r['amount'] for r in all_rows)
    today = datetime.now().strftime('%Y-%m-%d')
    today_total = sum(r['amount'] for r in all_rows if r['date'] == today)
    month = datetime.now().strftime('%Y-%m')
    month_total = sum(r['amount'] for r in all_rows if r['date'].startswith(month))
    avg = total / len(all_rows) if all_rows else 0

    status_counts = {}
    for s in ['pending_fm', 'pending_gm', 'fm_rejected', 'pending_payment', 'paid', 'gm_rejected']:
        status_counts[s] = sum(1 for r in all_rows if r['status'] == s)

    status_amounts = {}
    for s in ['pending_fm', 'pending_gm', 'fm_rejected', 'pending_payment', 'paid', 'gm_rejected']:
        status_amounts[s] = sum(r['amount'] for r in all_rows if r['status'] == s)

    # ── Breakdown by expense type: approved-not-paid vs paid ──
    type_breakdown = {}
    for r in all_rows:
        t = r['expense_type']
        if t not in type_breakdown:
            type_breakdown[t] = {'pending_payment': 0, 'paid': 0, 'total_approved': 0}
        if r['status'] == 'pending_payment':
            type_breakdown[t]['pending_payment'] += r['amount']
            type_breakdown[t]['total_approved'] += r['amount']
        elif r['status'] == 'paid':
            type_breakdown[t]['paid'] += r['amount']
            type_breakdown[t]['total_approved'] += r['amount']

    # ── Breakdown by branch: approved-not-paid vs paid ──
    branch_breakdown = {}
    for r in all_rows:
        b = r['branch']
        if b not in branch_breakdown:
            branch_breakdown[b] = {'pending_payment': 0, 'paid': 0}
        if r['status'] == 'pending_payment':
            branch_breakdown[b]['pending_payment'] += r['amount']
        elif r['status'] == 'paid':
            branch_breakdown[b]['paid'] += r['amount']

    type_totals = {}
    for r in all_rows:
        t = r['expense_type']
        type_totals[t] = type_totals.get(t, 0) + r['amount']

    branch_totals = {}
    for r in all_rows:
        b = r['branch']
        branch_totals[b] = branch_totals.get(b, 0) + r['amount']

    monthly = {}
    for r in all_rows:
        m = r['date'][:7]
        monthly[m] = monthly.get(m, 0) + r['amount']

    conn.close()
    return {
        'total': total,
        'today_total': today_total,
        'month_total': month_total,
        'avg': avg,
        'count': len(all_rows),
        'status_counts': status_counts,
        'status_amounts': status_amounts,
        'type_totals': sorted(type_totals.items(), key=lambda x: -x[1]),
        'branch_totals': sorted(branch_totals.items(), key=lambda x: -x[1]),
        'monthly': sorted(monthly.items()),
        'type_breakdown': type_breakdown,
        'branch_breakdown': branch_breakdown,
    }

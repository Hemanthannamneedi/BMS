from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from datetime import datetime
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = 'b7e2f8c1-4a2e-4c6e-9e3d-8f7a2c1e5b9d'

# MongoDB Atlas connection
client = MongoClient('mongodb+srv://gnana:Gnana1313@database.ryxtcce.mongodb.net/?retryWrites=true&w=majority&appName=Database')
db = client['student_club_db']

# Collections
club_members = db['club_members']
funds = db['funds']
requests_col = db['requests']
transactions = db['transactions']

# Admin credentials
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

# Helper: login required decorators
def login_required(role=None):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('login_member'))
            if role and session.get('role') != role:
                flash('Unauthorized access.')
                return redirect(url_for('login_member'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/features')
def features():
    return render_template('features.html')

@app.route('/about')
def about():
    return render_template('about.html')


# NEW: Route for Contact Us page
@app.route('/contact')
def contact():
    return render_template('contact.html')

# Admin login
@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['user'] = username
            session['role'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.')
    return render_template('login_admin.html')

# Member login
@app.route('/login_member', methods=['GET', 'POST'])
def login_member():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        member = club_members.find_one({'username': username, 'password': password, 'status': 'approved'})
        if member:
            session['user'] = username
            session['role'] = 'member'
            session['member_id'] = str(member['_id'])
            return redirect(url_for('member_dashboard'))
        else:
            flash('Invalid credentials or not approved yet.')
    return render_template('login_member.html')

# Member signup
@app.route('/signup_member', methods=['GET', 'POST'])
def signup_member():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        if club_members.find_one({'username': username}):
            flash('Username already exists.')
        else:
            club_members.insert_one({
                'username': username,
                'password': password,
                'name': name,
                'status': 'pending',
                'created_at': datetime.utcnow()
            })
            flash('Signup request submitted. Await admin approval.')
            return redirect(url_for('login_member'))
    return render_template('signup_member.html')

# Admin dashboard
@app.route('/admin_dashboard')
@login_required(role='admin')
def admin_dashboard():
    # Total funds
    fund_doc = funds.find_one()
    total_funds = fund_doc['total'] if fund_doc else 0
    # Transactions (latest first)
    txn_list = list(transactions.find().sort('timestamp', -1))
    for txn in txn_list:
        txn['date'] = txn['timestamp'].strftime('%Y-%m-%d %H:%M') if 'timestamp' in txn else ''
    # Pending members
    pending_members = list(club_members.find({'status': 'pending'}))
    # Fund requests (latest first)
    fund_requests = list(requests_col.find().sort('timestamp', -1))
    for req in fund_requests:
        member = club_members.find_one({'_id': req['member_id']})
        req['member_name'] = member['name'] if member else 'Unknown'
        req['date'] = req['date'] if 'date' in req else ''
        req['_id'] = str(req['_id'])
    for member in pending_members:
        member['_id'] = str(member['_id'])
    return render_template('admin_dashboard.html', total_funds=total_funds, transactions=txn_list, pending_members=pending_members, fund_requests=fund_requests)

@app.route('/add_offline_funds', methods=['POST'])
@login_required(role='admin')
def add_offline_funds():
    amount = float(request.form['amount'])
    source = request.form['source']
    # Update funds
    fund_doc = funds.find_one()
    if fund_doc:
        funds.update_one({'_id': fund_doc['_id']}, {'$inc': {'total': amount}})
    else:
        funds.insert_one({'total': amount})
    # Log transaction
    transactions.insert_one({
        'description': f'Offline funds added from {source}',
        'amount': amount,
        'timestamp': datetime.utcnow(),
        'type': 'add'
    })
    flash('Offline funds added successfully.')
    return redirect(url_for('admin_dashboard'))

@app.route('/approve_member/<member_id>', methods=['POST'])
@login_required(role='admin')
def approve_member(member_id):
    club_members.update_one({'_id': ObjectId(member_id)}, {'$set': {'status': 'approved'}})
    flash('Member approved.')
    return redirect(url_for('admin_dashboard'))

@app.route('/reject_member/<member_id>', methods=['POST'])
@login_required(role='admin')
def reject_member(member_id):
    club_members.update_one({'_id': ObjectId(member_id)}, {'$set': {'status': 'rejected'}})
    flash('Member rejected.')
    return redirect(url_for('admin_dashboard'))

@app.route('/approve_fund_request/<request_id>', methods=['POST'])
@login_required(role='admin')
def approve_fund_request(request_id):
    req = requests_col.find_one({'_id': ObjectId(request_id)})
    if not req or req['status'] != 'pending':
        flash('Invalid request.')
        return redirect(url_for('admin_dashboard'))
    amount = float(req['amount'])
    # Check available funds
    fund_doc = funds.find_one()
    if not fund_doc or fund_doc['total'] < amount:
        flash('Insufficient funds.')
        return redirect(url_for('admin_dashboard'))
    # Deduct funds
    funds.update_one({'_id': fund_doc['_id']}, {'$inc': {'total': -amount}})
    # Update request
    requests_col.update_one({'_id': ObjectId(request_id)}, {'$set': {'status': 'approved'}})
    # Log transaction
    transactions.insert_one({
        'description': f'Fund request approved for {amount} (Reason: {req["reason"]})',
        'amount': -amount,
        'timestamp': datetime.utcnow(),
        'type': 'expense'
    })
    flash('Fund request approved and amount deducted.')
    return redirect(url_for('admin_dashboard'))

@app.route('/reject_fund_request/<request_id>', methods=['POST'])
@login_required(role='admin')
def reject_fund_request(request_id):
    requests_col.update_one({'_id': ObjectId(request_id)}, {'$set': {'status': 'rejected'}})
    flash('Fund request rejected.')
    return redirect(url_for('admin_dashboard'))

# Member dashboard
@app.route('/member_dashboard', methods=['GET', 'POST'])
@login_required(role='member')
def member_dashboard():
    # Total funds
    fund_doc = funds.find_one()
    total_funds = fund_doc['total'] if fund_doc else 0
    # My requests
    my_requests = list(requests_col.find({'member_id': ObjectId(session['member_id'])}).sort('timestamp', -1))
    for req in my_requests:
        req['_id'] = str(req['_id'])
        req['date'] = req['date'] if 'date' in req else ''
    # Get member name
    member = club_members.find_one({'_id': ObjectId(session['member_id'])})
    member_name = member['name'] if member else session['user']
    return render_template('member_dashboard.html', total_funds=total_funds, my_requests=my_requests, member_name=member_name)

@app.route('/submit_fund_request', methods=['POST'])
@login_required(role='member')
def submit_fund_request():
    amount = float(request.form['amount'])
    reason = request.form['reason']
    date = request.form['date']
    requests_col.insert_one({
        'member_id': ObjectId(session['member_id']),
        'amount': amount,
        'reason': reason,
        'date': date,
        'status': 'pending',
        'timestamp': datetime.utcnow()
    })
    flash('Fund request submitted for approval.')
    return redirect(url_for('member_dashboard'))

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
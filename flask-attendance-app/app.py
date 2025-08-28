from flask import Flask, render_template, request, redirect, url_for, flash, make_response, session
from database import db
from models import Attendance, MeetingLocation, MeetingSession
from sqlalchemy.exc import IntegrityError
import qrcode
import io
import base64
from geopy.distance import geodesic
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# Admin configuration
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "attendance123"  # Change this in production!

# Database configuration
import os
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "attendance.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Admin access required. Please log in.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Successfully logged in as admin!', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash('Successfully logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/attendance')
def attendance_form():
    active_location = get_active_meeting_location()
    active_session = get_active_meeting_session()
    
    # If no active session, redirect to home with message
    if not active_session:
        flash('No active meeting session. Please check with the organizer.', 'error')
        return redirect(url_for('index'))
    
    response = make_response(render_template('attendance_form.html', active_location=active_location, active_session=active_session))
    # Prevent caching to ensure fresh data
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache' 
    response.headers['Expires'] = '0'
    return response

@app.route('/submit-attendance', methods=['POST'])
def submit_attendance():
    # Check if there's an active meeting session
    active_session = get_active_meeting_session()
    if not active_session:
        flash('No active meeting session. Please check with the organizer.', 'error')
        return redirect(url_for('index'))
    
    #get form data
    firstname = request.form['firstname']
    lastname = request.form['lastname']
    surname = request.form['surname']
    email = request.form['email']
    phone = request.form['phone']

    try:
        # Create a new Attendance record
        new_attendance = Attendance(
            firstname=firstname,
            lastname=lastname,
            surname=surname,
            email=email,
            phone=phone
        )

        #save to database
        db.session.add(new_attendance)
        db.session.commit()
        
        # Get meeting info for success page  
        active_location = get_active_meeting_location()
        current_count = get_current_attendance_count()

        # Redirect to success page with context (fix the URL parameters)
        meeting_name = active_location.name if active_location else 'the meeting'
        return redirect(url_for('success') + f'?meeting={meeting_name}&count={current_count}')
        
    except IntegrityError as e:
        # Handle duplicate email or phone
        db.session.rollback()
        error_message = str(e.orig)
        
        if 'attendance.email' in error_message:
            flash('This email address has already been registered for attendance.', 'error')
        elif 'attendance.phone' in error_message:
            flash('This phone number has already been registered for attendance.', 'error')
        else:
            flash('This information has already been registered. Please check your email or phone number.', 'error')
            
        return redirect(url_for('attendance_form'))

@app.route('/success')
def success():
    meeting_name = request.args.get('meeting', 'the meeting')
    attendance_count = request.args.get('count', '0')
    return render_template('success.html', meeting_name=meeting_name, attendance_count=attendance_count)

@app.route('/admin')
@admin_required
def admin():
    active_location = get_active_meeting_location()
    active_session = get_active_meeting_session()
    current_attendance_count = get_current_attendance_count()
    last_ended_session = get_last_ended_meeting_session()
    return render_template('admin.html', 
                         active_location=active_location, 
                         active_session=active_session,
                         attendance_count=current_attendance_count,
                         last_ended_session=last_ended_session)

@app.route('/generate-qr')
@admin_required
def generate_qr():
    # Force remote IP for QR codes so mobile devices can connect
    import socket
    try:
        # Better way to get network IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        remote_ip = s.getsockname()[0]
        s.close()
    except:
        # Fallback to hostname method
        hostname = socket.gethostname()
        remote_ip = socket.gethostbyname(hostname)
    
    base_url = f"http://{remote_ip}:5000"
    attendance_url = f"{base_url}{url_for('attendance_form')}"
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(attendance_url)
    qr.make(fit=True)

    # Create QR code image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to bytes
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    from flask import send_file
    return send_file(img_io, mimetype='image/png')

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in meters"""
    point1 = (lat1, lon1)
    point2 = (lat2, lon2)
    return geodesic(point1, point2).meters

def get_active_meeting_location():
    """Get the currently active meeting location"""
    return MeetingLocation.query.filter_by(is_active=True).first()

def get_active_meeting_session():
    """Get the currently active meeting session"""
    return MeetingSession.query.filter_by(is_active=True).first()

def get_last_ended_meeting_session():
    """Get the most recently ended meeting session"""
    return MeetingSession.query.filter_by(is_active=False).order_by(MeetingSession.end_time.desc()).first()

def get_current_attendance_count():
    """Get the count of attendees for the current (non-archived) session"""
    return Attendance.query.filter_by(is_archived=False).count()

def start_new_meeting_session(meeting_name, location_id):
    """Start a new meeting session"""
    # End any existing active sessions
    MeetingSession.query.filter_by(is_active=True).update({'is_active': False})
    
    # Create new session
    new_session = MeetingSession(
        meeting_name=meeting_name,
        location_id=location_id,
        is_active=True
    )
    db.session.add(new_session)
    db.session.commit()
    return new_session

def end_current_meeting_session():
    """End the current meeting and archive its attendance"""
    from datetime import datetime
    
    # Get current session
    current_session = get_active_meeting_session()
    if not current_session:
        return False
    
    # Archive all current attendance records
    current_attendees = Attendance.query.filter_by(is_archived=False).all()
    for attendee in current_attendees:
        attendee.is_archived = True
        attendee.meeting_session_id = current_session.id
    
    # End the session
    current_session.is_active = False
    current_session.end_time = datetime.now()
    current_session.attendee_count = len(current_attendees)
    
    db.session.commit()
    return True

@app.route('/location-setup')
@admin_required
def location_setup():
    active_location = get_active_meeting_location()
    return render_template('location_setup.html', active_location=active_location)

@app.route('/save-location', methods=['POST'])
@admin_required
def save_location():
    try:
        # Deactivate all existing locations
        MeetingLocation.query.update({'is_active': False})
        
        # Get form data
        name = request.form['name']
        address = request.form.get('address', '')  # Add address field
        latitude = float(request.form['latitude'])
        longitude = float(request.form['longitude'])
        radius = int(request.form.get('radius', 30))
        
        # Create new location
        new_location = MeetingLocation(
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius,
            is_active=True
        )
        
        db.session.add(new_location)
        db.session.commit()
        
        # Start a new meeting session for this location
        start_new_meeting_session(name, new_location.id)
        
        flash(f'Meeting location "{name}" has been set successfully! Generate QR code below.', 'success')
        return redirect(url_for('admin'))
        
    except ValueError:
        flash('Invalid coordinates. Please enter valid numbers.', 'error')
        return redirect(url_for('location_setup'))
    except Exception as e:
        flash(f'Error saving location: {str(e)}', 'error')
        return redirect(url_for('location_setup'))

@app.route('/start-meeting', methods=['GET', 'POST'])
@admin_required
def start_meeting():
    """Start a new meeting session using existing location"""
    active_location = get_active_meeting_location()
    if not active_location:
        flash('Please set up a meeting location first.', 'error')
        return redirect(url_for('location_setup'))
    
    if request.method == 'POST':
        meeting_name = request.form.get('meeting_name', '').strip()
        if not meeting_name:
            flash('Please enter a meeting name.', 'error')
            return render_template('start_meeting.html', location=active_location)
        
        try:
            # Start new meeting session
            start_new_meeting_session(meeting_name, active_location.id)
            flash(f'Meeting "{meeting_name}" started successfully!', 'success')
            return redirect(url_for('admin'))
        except Exception as e:
            flash(f'Error starting meeting: {str(e)}', 'error')
    
    return render_template('start_meeting.html', location=active_location)

@app.route('/end-meeting', methods=['POST'])
@admin_required
def end_meeting():
    """End the current meeting and archive attendance"""
    try:
        active_session = get_active_meeting_session()
        if not active_session:
            flash('No active meeting to end.', 'error')
            return redirect(url_for('admin'))
            
        attendee_count = get_current_attendance_count()
        meeting_name = active_session.meeting_name
        
        # End the meeting and archive data
        success = end_current_meeting_session()
        
        if success:
            flash(f'Meeting "{meeting_name}" has been ended successfully! {attendee_count} attendees archived.', 'success')
        else:
            flash('Error ending meeting.', 'error')
            
    except Exception as e:
        flash(f'Error ending meeting: {str(e)}', 'error')
    
    return redirect(url_for('admin'))

if __name__ == '__main__':
    import socket
    with app.app_context():
        # Create all tables (including new MeetingSession table)
        db.create_all()
        print("Database tables created successfully!")
    
    # Get local IP address for remote access
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("� Starting Flask for local network access...")
    print("🏠 Admin (Localhost): http://localhost:5000")
    print(f"📱 Remote (QR Codes): http://{local_ip}:5000")
    print("🌍 Fast and compatible with all browsers!")
    print("💡 Note: Geolocation requires HTTPS for internet deployment")
    print("=" * 60)
    
    # Use HTTP for better compatibility and speed on local networks
    app.run(host='0.0.0.0', debug=True, port=5000)
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, session, send_file
from database import db
from models import Attendance, MeetingLocation, MeetingSession
from sqlalchemy.exc import IntegrityError
import qrcode
import io
import base64
from geopy.distance import geodesic
from functools import wraps
import pandas as pd
from datetime import datetime
import tempfile
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# Admin configuration
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "attendance123"  # Change this in production!

# Database configuration
import os
basedir = os.path.abspath(os.path.dirname(__file__))

# Use a simple database path that works on Render
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "attendance.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Create database tables on startup and handle migrations
with app.app_context():
    try:
        # Try to create tables (handles new installations)
        db.create_all()
        
        # Check if we need to migrate existing attendance records
        # Add default values for new columns if they don't exist
        existing_records = db.session.execute(db.text("SELECT COUNT(*) FROM attendance")).scalar()
        if existing_records > 0:
            # Check if new columns exist
            try:
                db.session.execute(db.text("SELECT zone FROM attendance LIMIT 1"))
            except:
                # Add new columns with default values for existing records
                print("Adding new columns to existing attendance table...")
                db.session.execute(db.text("ALTER TABLE attendance ADD COLUMN zone VARCHAR(50) DEFAULT 'MCA'"))
                db.session.execute(db.text("ALTER TABLE attendance ADD COLUMN group_name VARCHAR(100) DEFAULT 'VIRTUOUS'"))
                db.session.execute(db.text("ALTER TABLE attendance ADD COLUMN church VARCHAR(200) DEFAULT 'Unknown'"))
                db.session.execute(db.text("ALTER TABLE attendance ADD COLUMN category VARCHAR(50) DEFAULT 'Member'"))
                db.session.commit()
                print("Database migration completed!")
        
        print("Database tables created/updated successfully!")
    except Exception as e:
        print(f"Database setup error: {e}")
        # Fallback: just create tables
        db.create_all()

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
    
    # Get form data
    firstname = request.form['firstname']
    lastname = request.form['lastname']
    surname = request.form['surname']
    email = request.form['email']
    phone = request.form['phone']
    zone = request.form['zone']
    group_name = request.form['group_name']
    church = request.form['church']
    category = request.form['category']
    user_latitude = request.form.get('latitude')
    user_longitude = request.form.get('longitude')
    # Geolocation enforcement disabled for this meeting
    user_lat = None
    user_lon = None

    try:
        # Get the active meeting session to link this attendance record
        active_session = get_active_meeting_session()
        
        # Create a new Attendance record
        new_attendance = Attendance(
            firstname=firstname,
            lastname=lastname,
            surname=surname,
            email=email,
            phone=phone,
            zone=zone,
            group_name=group_name,
            church=church,
            category=category,
            latitude=user_lat,
            longitude=user_lon,
            meeting_session_id=active_session.id if active_session else None
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
    
    # Get detailed counts
    zone_counts = get_attendance_counts_by_zone()
    group_counts = get_attendance_counts_by_group()
    category_counts = get_attendance_counts_by_category()
    
    return render_template('admin.html', 
                         active_location=active_location, 
                         active_session=active_session,
                         attendance_count=current_attendance_count,
                         last_ended_session=last_ended_session,
                         zone_counts=zone_counts,
                         group_counts=group_counts,
                         category_counts=category_counts)

@app.route('/generate-qr')
@admin_required
def generate_qr():
    # Use the current request's domain (works for both local and deployed)
    base_url = request.url_root.rstrip('/')
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

def get_attendance_counts_by_zone():
    """Get attendance counts by zone for current session"""
    active_session = get_active_meeting_session()
    if not active_session:
        return {}
    
    from sqlalchemy import func
    counts = db.session.query(
        Attendance.zone, 
        func.count(Attendance.id).label('count')
    ).filter(
        Attendance.meeting_session_id == active_session.id,
        Attendance.zone.isnot(None),
        Attendance.zone != ''
    ).group_by(Attendance.zone).all()
    
    return {zone: count for zone, count in counts}

def get_attendance_counts_by_group():
    """Get attendance counts by group for current session"""
    active_session = get_active_meeting_session()
    if not active_session:
        return {}
    
    from sqlalchemy import func
    counts = db.session.query(
        Attendance.group_name, 
        func.count(Attendance.id).label('count')
    ).filter(
        Attendance.meeting_session_id == active_session.id,
        Attendance.group_name.isnot(None),
        Attendance.group_name != ''
    ).group_by(Attendance.group_name).all()
    
    return {group: count for group, count in counts}

def get_attendance_counts_by_category():
    """Get attendance counts by category for current session"""
    active_session = get_active_meeting_session()
    if not active_session:
        return {}
    
    from sqlalchemy import func
    counts = db.session.query(
        Attendance.category, 
        func.count(Attendance.id).label('count')
    ).filter(
        Attendance.meeting_session_id == active_session.id,
        Attendance.category.isnot(None),
        Attendance.category != ''
    ).group_by(Attendance.category).all()
    
    return {category: count for category, count in counts}

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

@app.route('/clear-all-records', methods=['POST'])
@admin_required
def clear_all_records():
    """Clear all attendance records and meeting sessions - DANGEROUS!"""
    try:
        # Get counts before deletion
        attendance_count = Attendance.query.count()
        session_count = MeetingSession.query.count()
        
        # Delete all attendance records
        Attendance.query.delete()
        
        # Delete all meeting sessions
        MeetingSession.query.delete()
        
        # Commit the changes
        db.session.commit()
        
        flash(f'Successfully cleared all data! Deleted {attendance_count} attendance records and {session_count} meeting sessions.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing records: {str(e)}', 'error')
    
    return redirect(url_for('admin'))

@app.route('/archived-records')
@admin_required
def archived_records():
    """View all archived meeting sessions and their attendance records"""
    # Get all ended meeting sessions (archived)
    archived_sessions = MeetingSession.query.filter_by(is_active=False).order_by(MeetingSession.end_time.desc()).all()
    
    # Get summary stats for each session
    session_data = []
    for session in archived_sessions:
        attendee_records = Attendance.query.filter_by(meeting_session_id=session.id).all()
        
        # Count by organizational structure
        zone_counts = {}
        group_counts = {}
        category_counts = {}
        
        for attendee in attendee_records:
            # Count zones
            if attendee.zone:
                zone_counts[attendee.zone] = zone_counts.get(attendee.zone, 0) + 1
            
            # Count groups
            if attendee.group_name:
                group_counts[attendee.group_name] = group_counts.get(attendee.group_name, 0) + 1
            
            # Count categories
            if attendee.category:
                category_counts[attendee.category] = category_counts.get(attendee.category, 0) + 1
        
        session_data.append({
            'session': session,
            'attendees': attendee_records,
            'total_count': len(attendee_records),
            'zone_counts': zone_counts,
            'group_counts': group_counts,
            'category_counts': category_counts
        })
    
    return render_template('archived_records.html', session_data=session_data)

@app.route('/download-archived-data/<format>')
@admin_required
def download_archived_data(format):
    """Download archived attendance data in CSV or Excel format"""
    if format not in ['csv', 'excel']:
        flash('Invalid download format. Please choose CSV or Excel.', 'error')
        return redirect(url_for('archived_records'))
    
    # Get all ended meeting sessions and their attendance data
    archived_sessions = MeetingSession.query.filter_by(is_active=False).order_by(MeetingSession.end_time.desc()).all()
    
    # Prepare data for export
    export_data = []
    for session in archived_sessions:
        attendees = Attendance.query.filter_by(meeting_session_id=session.id).all()
        
        for attendee in attendees:
            export_data.append({
                'Meeting Name': session.meeting_name,
                'Meeting Date': session.start_time.strftime('%Y-%m-%d') if session.start_time else 'N/A',
                'Meeting Start Time': session.start_time.strftime('%H:%M:%S') if session.start_time else 'N/A',
                'Meeting End Time': session.end_time.strftime('%H:%M:%S') if session.end_time else 'N/A',
                'Attendee Name': f"{attendee.firstname} {attendee.lastname} {attendee.surname}".strip(),
                'Email': attendee.email,
                'Phone': attendee.phone,
                'Zone': attendee.zone or 'Not Specified',
                'Group': attendee.group_name or 'Not Specified',
                'Church': attendee.church or 'Not Specified',
                'Category': attendee.category or 'Not Specified',
                'Registration Time': attendee.timestamp.strftime('%Y-%m-%d %H:%M:%S') if attendee.timestamp else 'N/A',
                'Location': f"{attendee.latitude}, {attendee.longitude}" if attendee.latitude and attendee.longitude else 'Not Available'
            })
    
    if not export_data:
        flash('No archived data available for download.', 'warning')
        return redirect(url_for('archived_records'))
    
    # Create DataFrame
    df = pd.DataFrame(export_data)
    
    # Generate filename with current timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if format == 'csv':
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8') as tmp_file:
            df.to_csv(tmp_file, index=False)
            temp_filename = tmp_file.name
        
        filename = f'attendance_archive_{timestamp}.csv'
        mimetype = 'text/csv'
        
    else:  # excel format
        # Create temporary Excel file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            df.to_excel(tmp_file.name, index=False, engine='openpyxl')
            temp_filename = tmp_file.name
        
        filename = f'attendance_archive_{timestamp}.xlsx'
        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    def remove_temp_file():
        try:
            os.unlink(temp_filename)
        except:
            pass
    
    # Schedule temp file cleanup after response
    response = make_response(send_file(temp_filename, mimetype=mimetype, as_attachment=True, download_name=filename))
    
    # Clean up temp file in background (this is a simple approach)
    # In production, you might want a more robust cleanup mechanism
    try:
        os.unlink(temp_filename)
    except:
        pass  # File might already be deleted
    
    return response

@app.route('/download-single-session/<int:session_id>/<format>')
@admin_required
def download_single_session(session_id, format):
    """Download a single session's attendance data in CSV or Excel format"""
    if format not in ['csv', 'excel']:
        flash('Invalid download format. Please choose CSV or Excel.', 'error')
        return redirect(url_for('archived_records'))
    
    # Get the specific session
    session_data = MeetingSession.query.get_or_404(session_id)
    attendees = Attendance.query.filter_by(meeting_session_id=session_id).all()
    
    if not attendees:
        flash('No attendance data found for this session.', 'warning')
        return redirect(url_for('archived_records'))
    
    # Prepare data for export
    export_data = []
    for attendee in attendees:
        export_data.append({
            'Meeting Name': session_data.meeting_name,
            'Meeting Date': session_data.start_time.strftime('%Y-%m-%d') if session_data.start_time else 'N/A',
            'Meeting Start Time': session_data.start_time.strftime('%H:%M:%S') if session_data.start_time else 'N/A',
            'Meeting End Time': session_data.end_time.strftime('%H:%M:%S') if session_data.end_time else 'N/A',
            'Attendee Name': f"{attendee.firstname} {attendee.lastname} {attendee.surname}".strip(),
            'Email': attendee.email,
            'Phone': attendee.phone,
            'Zone': attendee.zone or 'Not Specified',
            'Group': attendee.group_name or 'Not Specified',
            'Church': attendee.church or 'Not Specified',
            'Category': attendee.category or 'Not Specified',
            'Registration Time': attendee.timestamp.strftime('%Y-%m-%d %H:%M:%S') if attendee.timestamp else 'N/A',
            'Location': f"{attendee.latitude}, {attendee.longitude}" if attendee.latitude and attendee.longitude else 'Not Available'
        })
    
    # Create DataFrame
    df = pd.DataFrame(export_data)
    
    # Generate filename with session name and timestamp
    safe_session_name = "".join(c for c in session_data.meeting_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if format == 'csv':
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8') as tmp_file:
            df.to_csv(tmp_file, index=False)
            temp_filename = tmp_file.name
        
        filename = f'{safe_session_name}_attendance_{timestamp}.csv'
        mimetype = 'text/csv'
        
    else:  # excel format
        # Create temporary Excel file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
            df.to_excel(tmp_file.name, index=False, engine='openpyxl')
            temp_filename = tmp_file.name
        
        filename = f'{safe_session_name}_attendance_{timestamp}.xlsx'
        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    # Schedule temp file cleanup after response
    response = make_response(send_file(temp_filename, mimetype=mimetype, as_attachment=True, download_name=filename))
    
    # Clean up temp file
    try:
        os.unlink(temp_filename)
    except:
        pass
    
    return response

@app.route('/view-live-attendees')
@admin_required
def view_live_attendees():
    """Show all attendee details for the current active meeting session"""
    active_session = get_active_meeting_session()
    if not active_session:
        flash('No active meeting session found.', 'error')
        return redirect(url_for('admin'))
    attendees = Attendance.query.filter_by(meeting_session_id=active_session.id, is_archived=False).all()
    return render_template('live_attendees.html', attendees=attendees, meeting_name=active_session.meeting_name)

@app.route('/clear-meeting-record/<int:session_id>', methods=['POST'])
@admin_required
def clear_meeting_record(session_id):
    """Delete a specific meeting session and all its attendance records"""
    try:
        # Delete attendance records for this session
        Attendance.query.filter_by(meeting_session_id=session_id).delete()
        # Delete the meeting session itself
        MeetingSession.query.filter_by(id=session_id).delete()
        db.session.commit()
        flash('Meeting and its records deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting meeting record: {str(e)}', 'error')
    return redirect(url_for('archived_records'))

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
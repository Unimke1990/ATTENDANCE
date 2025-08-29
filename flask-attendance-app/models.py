from database import db

class MeetingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_name = db.Column(db.String(200), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('meeting_location.id'), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    end_time = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    attendee_count = db.Column(db.Integer, default=0)
    
    # Relationship
    location = db.relationship('MeetingLocation', backref='sessions')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    firstname = db.Column(db.String(100), nullable=False)
    lastname = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), unique=True)
    phone = db.Column(db.String(20), nullable=False, unique=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # New organizational fields
    zone = db.Column(db.String(50), nullable=False)  # MCA, ZONE 1, ZONE 2
    group_name = db.Column(db.String(100), nullable=False)  # VIRTUOUS, AUXANO, etc.
    church = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Leader, Member, Volunteer
    
    # Archiving fields
    meeting_session_id = db.Column(db.Integer, db.ForeignKey('meeting_session.id'), nullable=True)
    is_archived = db.Column(db.Boolean, default=False)
    
    # Relationship
    meeting_session = db.relationship('MeetingSession', backref='attendees')

class MeetingLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500), nullable=True)  # Add address field
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_meters = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
# Flask Attendance Tracker

A web-based attendance system using QR codes and GPS location validation.

## Features

- **Admin Dashboard**: Secure login and meeting management
- **QR Code Generation**: Dynamic QR codes for attendance
- **GPS Validation**: 30-meter radius location checking
- **Mobile Friendly**: Responsive design for all devices
- **Database Storage**: SQLite database with attendance records

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Unimke1990/ATTENDANCE.git
   cd ATTENDANCE
   ```

2. Install dependencies:
   ```bash
   pip install flask sqlalchemy qrcode[pil] geopy
   ```

3. Run the application:
   ```bash
   python app.py
   ```

4. Access at `http://localhost:5000`
   - Admin login: `admin` / `attendance123`

## How It Works

**Admin:**
1. Login to admin dashboard
2. Set meeting location using GPS
3. Generate QR code for the meeting
4. Monitor attendance in real-time

**Attendees:**
1. Scan QR code with phone
2. Fill out attendance form
3. Allow location access for validation
4. Submit attendance (validated within 30-meter radius)

## Tech Stack

- **Backend:** Flask, SQLAlchemy
- **Database:** SQLite
- **QR Codes:** qrcode library
- **Location:** geopy for GPS validation
- **Frontend:** HTML, CSS, JavaScript

## Author

**AGIM UNIMKE AGBA**
- Email: agimagba1990@gmail.com
- GitHub: [@Unimke1990](https://github.com/Unimke1990)

## License

MIT License

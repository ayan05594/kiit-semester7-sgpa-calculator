# Semester VII SGPA Calculator

A comprehensive SGPA (Semester Grade Point Average) calculator for KIIT University's Semester VII (B. Tech. Hons.) curriculum with backend support for record management.

## Features

- **Accurate SGPA Calculation**: Based on the official KIIT University Semester VII curriculum
- **Subject Management**: Handles both mandatory and optional subjects
- **Record Keeping**: Save and export student records
- **Real-time Validation**: Email validation and input checking
- **Modern UI**: Beautiful, responsive design with animations
- **Backend Support**: Node.js server for data persistence

## Subjects Included

### Theory Subjects (8 Credits Total)
- **Professional Elective-IV** (3 Credits)
- **Engineering Professional Practice (EX40003)** (2 Credits)
- **Open Elective-III / MI-II** (3 Credits)
- **Minor-III** (3 Credits) - Optional
- **Minor-IV** (3 Credits) - Optional

### Sessional Subjects (10 Credits Total)
- **Project-I (CS47001)** (5 Credits)
- **Internship (CS48001)** (2 Credits)
- **MI- (Computing Laboratory) (CS39008)** (2 Credits)

**Total Credits**: 15 (without optional subjects) or up to 21 (with both optional subjects)

## Installation & Setup

### Prerequisites
- Node.js (version 14 or higher)
- npm (Node Package Manager)
- Web browser

### Backend Setup

1. **Install Dependencies**
   ```bash
   npm install
   ```

2. **Start the Server**
   ```bash
   npm start
   ```
   
   Or for development with auto-restart:
   ```bash
   npm run dev
   ```

3. **Server Information**
   - Server runs on: `http://localhost:3000`
   - Records are saved to: `sgpa_records.json`
   - CORS enabled for frontend integration

### Frontend Setup

1. **Open the HTML File**
   - Open `semester_7_sgpa_calculator.html` in your web browser
   - Or serve it through a local web server for best results

2. **Background Image (Optional)**
   - Add a `bg.jpeg` file in the same directory for custom background
   - The calculator works without this image

## Usage

### For Students

1. **Enter Personal Information**
   - Name: Your full name
   - Email: Must end with `@kiit.ac.in`

2. **Select Grades**
   - Choose grades for each subject from dropdown menus
   - Optional subjects can be left unselected if not taken
   - Grade scale: O(10), E(9), A(8), B(7), C(6), D(5)

3. **Calculate SGPA**
   - Click "Calculate SGPA" button
   - View detailed breakdown of calculation
   - See total credits and grade points

4. **Export Records**
   - Click "Export Records" to download all saved records
   - Records are saved automatically when SGPA is calculated

### Grade Point System

| Grade | Points | Description |
|-------|--------|-------------|
| O     | 10     | Outstanding |
| E     | 9      | Excellent   |
| A     | 8      | Very Good   |
| B     | 7      | Good        |
| C     | 6      | Average     |
| D     | 5      | Below Average |

### SGPA Calculation Formula

```
SGPA = (Sum of (Grade Points × Credits)) / Total Credits
```

## API Endpoints

The backend server provides the following REST API endpoints:

### GET /
- **Description**: Server information and available endpoints
- **Response**: JSON with server status and endpoint list

### POST /save-record
- **Description**: Save a new SGPA record
- **Body**: 
  ```json
  {
    "name": "Student Name",
    "email": "student@kiit.ac.in",
    "sgpa": "8.75",
    "totalCredits": 18,
    "subjects": [...],
    "timestamp": "12/25/2023, 10:30:00 AM"
  }
  ```
- **Response**: Success message with record ID

### GET /get-records
- **Description**: Retrieve all saved records
- **Response**: Array of all SGPA records

### GET /stats
- **Description**: Get statistics about saved records
- **Response**: 
  ```json
  {
    "totalRecords": 25,
    "averageSGPA": 8.45,
    "highestSGPA": 9.8,
    "lowestSGPA": 6.2,
    "gradeDistribution": {...},
    "recentRecords": [...]
  }
  ```

### DELETE /delete-record/:id
- **Description**: Delete a specific record
- **Parameters**: Record ID
- **Response**: Success message

## File Structure

```
├── semester_7_sgpa_calculator.html  # Frontend application
├── server.js                        # Backend server
├── package.json                     # Node.js dependencies
├── sgpa_records.json                # Data storage (auto-created)
├── SGPA_CALCULATOR_README.md        # This file
└── bg.jpeg                          # Background image (optional)
```

## Features in Detail

### Frontend Features
- **Responsive Design**: Works on desktop and mobile devices
- **Real-time Validation**: Immediate feedback on input errors
- **Dynamic Credit Calculation**: Updates total credits based on selected subjects
- **Detailed Results**: Shows breakdown of calculation
- **Export Functionality**: Download records as text file
- **Modern Animations**: Smooth transitions and effects

### Backend Features
- **Data Persistence**: Records saved to JSON file
- **CORS Support**: Cross-origin requests enabled
- **Error Handling**: Comprehensive error management
- **Input Validation**: Server-side validation for data integrity
- **Statistics**: Automatic calculation of grade statistics
- **RESTful API**: Standard HTTP methods and status codes

## Customization

### Adding New Subjects
1. Update the HTML form with new subject inputs
2. Modify the `credits` object in JavaScript
3. Update the calculation logic if needed

### Changing Grade Scale
1. Modify the `gradePoints` object in JavaScript
2. Update dropdown options in HTML
3. Adjust validation logic if needed

### Styling Changes
1. Edit the CSS styles in the `<style>` section
2. Modify colors, fonts, and animations as desired
3. Add custom background images

## Troubleshooting

### Common Issues

1. **Server Won't Start**
   - Check if Node.js is installed: `node --version`
   - Install dependencies: `npm install`
   - Check if port 3000 is available

2. **Records Not Saving**
   - Ensure server is running
   - Check browser console for errors
   - Verify email format (@kiit.ac.in)

3. **Export Not Working**
   - Server must be running for export functionality
   - Check network connection
   - Ensure records exist in database

4. **Calculation Errors**
   - Verify all required fields are filled
   - Check grade selections
   - Ensure at least one subject is selected

### Browser Compatibility
- Chrome (recommended)
- Firefox
- Safari
- Edge

### Performance Notes
- Frontend works offline (except record saving/export)
- Server handles multiple concurrent requests
- Records file grows with usage (consider periodic cleanup)

## Contributing

Feel free to contribute improvements:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - feel free to use and modify as needed.

## Contact

- **Developer**: Ayan
- **Email**: ayan05594@gmail.com
- **Instagram**: [@ahhyhonn](https://www.instagram.com/ahhyhonn/)

## Acknowledgments

- KIIT University for the curriculum structure
- Students who provided feedback and testing
- Open source community for tools and libraries

---

**Note**: This calculator is based on the official KIIT University Semester VII curriculum. Always verify calculations with official university guidelines.

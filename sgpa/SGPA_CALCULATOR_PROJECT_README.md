# 🎓 KIIT University Semester VII SGPA Calculator

A comprehensive, modern SGPA (Semester Grade Point Average) calculator for KIIT University's Semester VII (B. Tech. Hons.) curriculum with full-stack support for record management and analytics.

![SGPA Calculator](https://img.shields.io/badge/SGPA-Calculator-blue?style=for-the-badge)
![KIIT University](https://img.shields.io/badge/KIIT-University-green?style=for-the-badge)
![Node.js](https://img.shields.io/badge/Node.js-Backend-brightgreen?style=for-the-badge)
![HTML5](https://img.shields.io/badge/HTML5-Frontend-orange?style=for-the-badge)

## ✨ Features

- 🎯 **Accurate SGPA Calculation** - Based on official KIIT University Semester VII curriculum
- 📚 **Complete Subject Coverage** - All theory and sessional subjects included
- 💾 **Record Management** - Save, view, and export student records
- 📊 **Analytics Dashboard** - Statistics and grade distribution
- 🎨 **Modern UI/UX** - Beautiful, responsive design with animations
- ✅ **Input Validation** - Real-time validation and error checking
- 📱 **Mobile Responsive** - Works perfectly on all devices
- 🔒 **KIIT Email Validation** - Ensures authentic university emails

## 📋 Subjects Included

### Theory Subjects (8 Credits)
- **Professional Elective-IV** (3 Credits)
- **Engineering Professional Practice (EX40003)** (2 Credits)  
- **Open Elective-III / MI-II** (3 Credits)
- **Minor-III** (3 Credits) - *Optional*
- **Minor-IV** (3 Credits) - *Optional*

### Sessional Subjects (10 Credits)
- **Project-I (CS47001)** (5 Credits)
- **Internship (CS48001)** (2 Credits)
- **MI- (Computing Laboratory) (CS39008)** (2 Credits)

**Total Credits**: 15-21 (depending on optional subjects)

## 🚀 Quick Start

### Prerequisites
- Node.js (v14 or higher)
- npm (Node Package Manager)
- Modern web browser

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/kiit-semester7-sgpa-calculator.git
   cd kiit-semester7-sgpa-calculator
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Start the backend server**
   ```bash
   npm start
   ```

4. **Open the calculator**
   - Open `semester_7_sgpa_calculator.html` in your web browser
   - Server runs on `http://localhost:3000`

## 📖 Usage

1. **Enter Your Details**
   - Full name
   - KIIT email address (must end with @kiit.ac.in)

2. **Select Grades**
   - Choose grades for each subject from dropdown menus
   - Optional subjects can be left unselected
   - Grade scale: O(10), E(9), A(8), B(7), C(6), D(5)

3. **Calculate SGPA**
   - Click "Calculate SGPA" to see detailed results
   - View breakdown of calculation with grade points

4. **Export Records**
   - All calculations are automatically saved
   - Export all records as a text file

## 🏗️ Project Structure

```
├── semester_7_sgpa_calculator.html  # Frontend application
├── server.js                        # Backend API server
├── package.json                     # Dependencies & scripts
├── .gitignore                       # Git ignore rules
└── SGPA_CALCULATOR_README.md        # Detailed documentation
```

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Server information |
| POST | `/save-record` | Save SGPA record |
| GET | `/get-records` | Retrieve all records |
| GET | `/stats` | Get statistics |
| DELETE | `/delete-record/:id` | Delete specific record |

## 📊 Grade Point System

| Grade | Points | Description |
|-------|--------|-------------|
| O | 10 | Outstanding |
| E | 9 | Excellent |
| A | 8 | Very Good |
| B | 7 | Good |
| C | 6 | Average |
| D | 5 | Below Average |

## 🧮 SGPA Formula

```
SGPA = Σ(Grade Points × Credits) / Total Credits
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License.

## 👨‍💻 Author

**Ayan**
- Email: ayan05594@gmail.com
- Instagram: [@ahhyhonn](https://www.instagram.com/ahhyhonn/)

## 🙏 Acknowledgments

- KIIT University for the curriculum structure
- Students who provided feedback and testing
- Open source community for tools and libraries

## ⚠️ Disclaimer

This calculator is based on the official KIIT University Semester VII curriculum. Always verify calculations with official university guidelines.

---

⭐ **Star this repository if you found it helpful!**

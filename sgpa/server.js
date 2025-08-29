const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');

const app = express();
const PORT = 3000;
const RECORDS_FILE = path.join(__dirname, 'sgpa_records.json');

// Middleware
app.use(cors());
app.use(express.json());

// Initialize records file if it doesn't exist
async function initializeRecordsFile() {
  try {
    await fs.access(RECORDS_FILE);
  } catch (error) {
    // File doesn't exist, create it with empty array
    await fs.writeFile(RECORDS_FILE, JSON.stringify([], null, 2));
    console.log('Created new records file');
  }
}

// Read records from file
async function readRecords() {
  try {
    const data = await fs.readFile(RECORDS_FILE, 'utf8');
    return JSON.parse(data);
  } catch (error) {
    console.error('Error reading records:', error);
    return [];
  }
}

// Write records to file
async function writeRecords(records) {
  try {
    await fs.writeFile(RECORDS_FILE, JSON.stringify(records, null, 2));
  } catch (error) {
    console.error('Error writing records:', error);
    throw error;
  }
}

// Routes
app.get('/', (req, res) => {
  res.json({ 
    message: 'SGPA Calculator Server is running!',
    endpoints: {
      'POST /save-record': 'Save a new SGPA record',
      'GET /get-records': 'Get all saved records',
      'GET /stats': 'Get statistics about saved records'
    }
  });
});

// Save a new record
app.post('/save-record', async (req, res) => {
  try {
    const { name, email, sgpa, totalCredits, subjects, timestamp } = req.body;
    
    // Validate required fields
    if (!name || !email || !sgpa) {
      return res.status(400).json({ 
        error: 'Missing required fields: name, email, and sgpa are required' 
      });
    }

    // Validate email format
    if (!email.endsWith('@kiit.ac.in')) {
      return res.status(400).json({ 
        error: 'Email must end with @kiit.ac.in' 
      });
    }

    const records = await readRecords();
    
    const newRecord = {
      id: Date.now().toString(),
      name,
      email,
      sgpa: parseFloat(sgpa),
      totalCredits: totalCredits || 0,
      subjects: subjects || [],
      timestamp: timestamp || new Date().toLocaleString(),
      createdAt: new Date().toISOString()
    };

    records.push(newRecord);
    await writeRecords(records);

    res.json({ 
      message: 'Record saved successfully!', 
      recordId: newRecord.id,
      totalRecords: records.length
    });
  } catch (error) {
    console.error('Error saving record:', error);
    res.status(500).json({ error: 'Failed to save record' });
  }
});

// Get all records
app.get('/get-records', async (req, res) => {
  try {
    const records = await readRecords();
    res.json(records);
  } catch (error) {
    console.error('Error fetching records:', error);
    res.status(500).json({ error: 'Failed to fetch records' });
  }
});

// Get statistics
app.get('/stats', async (req, res) => {
  try {
    const records = await readRecords();
    
    if (records.length === 0) {
      return res.json({
        totalRecords: 0,
        averageSGPA: 0,
        highestSGPA: 0,
        lowestSGPA: 0
      });
    }

    const sgpaValues = records.map(record => parseFloat(record.sgpa));
    const averageSGPA = sgpaValues.reduce((sum, sgpa) => sum + sgpa, 0) / sgpaValues.length;
    const highestSGPA = Math.max(...sgpaValues);
    const lowestSGPA = Math.min(...sgpaValues);

    // Grade distribution
    const gradeDistribution = {};
    sgpaValues.forEach(sgpa => {
      let grade;
      if (sgpa >= 9.5) grade = 'O';
      else if (sgpa >= 8.5) grade = 'E';
      else if (sgpa >= 7.5) grade = 'A';
      else if (sgpa >= 6.5) grade = 'B';
      else if (sgpa >= 5.5) grade = 'C';
      else grade = 'D';
      
      gradeDistribution[grade] = (gradeDistribution[grade] || 0) + 1;
    });

    res.json({
      totalRecords: records.length,
      averageSGPA: parseFloat(averageSGPA.toFixed(2)),
      highestSGPA,
      lowestSGPA,
      gradeDistribution,
      recentRecords: records.slice(-5).reverse() // Last 5 records
    });
  } catch (error) {
    console.error('Error generating stats:', error);
    res.status(500).json({ error: 'Failed to generate statistics' });
  }
});

// Delete a record (optional feature)
app.delete('/delete-record/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const records = await readRecords();
    
    const filteredRecords = records.filter(record => record.id !== id);
    
    if (filteredRecords.length === records.length) {
      return res.status(404).json({ error: 'Record not found' });
    }
    
    await writeRecords(filteredRecords);
    
    res.json({ 
      message: 'Record deleted successfully!',
      totalRecords: filteredRecords.length
    });
  } catch (error) {
    console.error('Error deleting record:', error);
    res.status(500).json({ error: 'Failed to delete record' });
  }
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Internal server error' });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Endpoint not found' });
});

// Start server
async function startServer() {
  try {
    await initializeRecordsFile();
    
    app.listen(PORT, () => {
      console.log(`🚀 SGPA Calculator Server is running on http://localhost:${PORT}`);
      console.log(`📊 Records will be saved to: ${RECORDS_FILE}`);
      console.log(`🌐 CORS enabled for frontend integration`);
      console.log(`\nAvailable endpoints:`);
      console.log(`  GET  /              - Server info`);
      console.log(`  POST /save-record   - Save SGPA record`);
      console.log(`  GET  /get-records   - Get all records`);
      console.log(`  GET  /stats         - Get statistics`);
      console.log(`  DELETE /delete-record/:id - Delete record`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

startServer();

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n🛑 Server shutting down gracefully...');
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n🛑 Server shutting down gracefully...');
  process.exit(0);
});

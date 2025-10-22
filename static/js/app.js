// ===== SOCKET.IO CONNECTION =====
const socket = io();

// Biến trạng thái
let isAutoMode = false;
let startTime = Date.now();

// Xử lý kết nối Socket.IO
socket.on('connect', function() {
    console.log('Connected to server');
    updateConnectionStatus(true);
});

socket.on('disconnect', function() {
    console.log('Disconnected from server');
    updateConnectionStatus(false);
});

// Nhận dữ liệu sensor từ server
socket.on('sensor_update', function(data) {
    console.log('Sensor data received:', data);
    updateSensorData(data);
});

// Nhận cập nhật mode từ server
socket.on('mode_update', function(data) {
    console.log('Mode update received:', data);
    if (data.mode) {
        isAutoMode = (data.mode === 'auto');
        const modeAuto = document.getElementById('modeAuto');
        const modeManual = document.getElementById('modeManual');
        
        if (isAutoMode) {
            modeAuto.checked = true;
        } else {
            modeManual.checked = true;
        }
        
        updateControlsState();
    }
});

// Nhận log entries từ server
socket.on('log_entry', function(data) {
    addLogEntry(data.time, data.level, data.message);
});

// ===== CONNECTION STATUS =====
function updateConnectionStatus(isConnected) {
    const badge = document.getElementById('connectionBadge');
    const text = document.getElementById('connectionText');
    
    if (isConnected) {
        badge.classList.remove('offline');
        text.textContent = 'Connected';
    } else {
        badge.classList.add('offline');
        text.textContent = 'Disconnected';
    }
}

// ===== SENSOR DATA UPDATE =====
function updateSensorData(data) {
    // Cập nhật Battery
    if (data.battery !== undefined) {
        const batteryBar = document.getElementById('batteryBar');
        const batteryValue = document.getElementById('batteryValue');
        batteryBar.style.width = data.battery + '%';
        batteryValue.textContent = data.battery + '%';
    }
    
    // Cập nhật Speed
    if (data.speed !== undefined) {
        const speedBar = document.getElementById('speedBar');
        const speedValue = document.getElementById('speedValue');
        const percentage = (data.speed / 255 * 100).toFixed(0);
        speedBar.style.width = percentage + '%';
        speedValue.textContent = data.speed + '/255';
    }
    
    // Cập nhật Temperature
    if (data.temperature !== undefined) {
        document.getElementById('tempValue').textContent = data.temperature + '°C';
    }
    
    // Cập nhật State
    if (data.state !== undefined) {
        const stateValue = document.getElementById('stateValue');
        const stateDot = document.getElementById('stateDot');
        stateValue.textContent = data.state;
        
        // Màu state dot theo trạng thái
        stateDot.style.background = getStateColor(data.state);
    }
    
    // Cập nhật Line Sensors
    if (data.line_sensors !== undefined) {
        updateLineSensors(data.line_sensors);
    }
    
    // Cập nhật Line Position
    if (data.line_position !== undefined) {
        document.getElementById('linePosition').textContent = 
            (data.line_position > 0 ? '+' : '') + data.line_position;
    }
    
    // Cập nhật Ultrasonic Distance
    if (data.distance !== undefined) {
        const distValue = document.getElementById('ultrasonicValue');
        const distBar = document.getElementById('distanceBar');
        distValue.textContent = data.distance.toFixed(1);
        
        // Distance bar: 0-100cm range
        const percentage = Math.min(100, data.distance);
        distBar.style.width = percentage + '%';
    }
    
    // Cập nhật Detections
    if (data.detection !== undefined) {
        addDetection(data.detection);
    }
}

// ===== STATE COLOR =====
function getStateColor(state) {
    const colors = {
        'IDLE': '#gray',
        'FOLLOWING LINE': '#4caf50',
        'OBSTACLE DETECTED': '#ff9800',
        'STOPPED': '#f44336',
        'TURNING': '#2196f3'
    };
    return colors[state] || '#4caf50';
}

// ===== UPDATE LINE SENSORS =====
function updateLineSensors(sensors) {
    const sensorBars = document.querySelectorAll('.sensor-bar');
    sensors.forEach((value, index) => {
        if (index < sensorBars.length) {
            if (value) {
                sensorBars[index].classList.add('active');
            } else {
                sensorBars[index].classList.remove('active');
            }
        }
    });
}

// ===== ADD DETECTION =====
function addDetection(detection) {
    const detectionList = document.getElementById('detectionList');
    const now = new Date();
    const timeStr = now.toLocaleTimeString('vi-VN', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
    
    const item = document.createElement('div');
    item.className = 'detection-item';
    item.innerHTML = `
        <span class="detection-time">${timeStr}</span>
        <span class="detection-object">${detection.object}</span>
        <span class="detection-confidence">${detection.confidence ? detection.confidence + '%' : '--'}</span>
    `;
    
    // Thêm vào đầu danh sách
    detectionList.insertBefore(item, detectionList.firstChild);
    
    // Giữ tối đa 5 items
    while (detectionList.children.length > 5) {
        detectionList.removeChild(detectionList.lastChild);
    }
}

// ===== ROBOT CONTROL COMMANDS =====
function sendCommand(command) {
    // Kiểm tra mode trước khi gửi lệnh
    if (isAutoMode) {
        console.log('Cannot send command in Auto mode');
        addLogEntry(new Date().toLocaleTimeString(), 'WARNING', 
            'Manual control disabled in Auto mode');
        return;
    }
    
    fetch('/' + command)
        .then(response => {
            if (!response.ok) {
                throw new Error('Command failed');
            }
            return response.json();
        })
        .then(data => {
            console.log('Command sent:', command, 'Response:', data);
            if (data.status === 'error') {
                addLogEntry(new Date().toLocaleTimeString(), 'ERROR', data.message);
            }
        })
        .catch(error => {
            console.error('Error sending command:', error);
            addLogEntry(new Date().toLocaleTimeString(), 'ERROR', 
                'Failed to send command: ' + command);
        });
}

// ===== EMERGENCY STOP =====
function emergencyStop() {
    if (confirm('Execute EMERGENCY STOP?')) {
        fetch('/emergency_stop')
            .then(response => response.json())
            .then(data => {
                console.log('Emergency stop executed:', data);
                addLogEntry(new Date().toLocaleTimeString(), 'WARNING', 
                    'EMERGENCY STOP executed');
            })
            .catch(error => {
                console.error('Error executing emergency stop:', error);
            });
    }
}

// ===== MODE TOGGLE =====
function toggleMode() {
    const modeAuto = document.getElementById('modeAuto');
    isAutoMode = modeAuto.checked;
    
    const mode = isAutoMode ? 'auto' : 'manual';
    
    // Gửi request đến server
    fetch('/set_mode?mode=' + mode)
        .then(response => response.json())
        .then(data => {
            console.log('Mode changed to:', mode, data);
            addLogEntry(new Date().toLocaleTimeString(), 'INFO', 
                'Mode changed to: ' + mode.toUpperCase());
            updateControlsState();
        })
        .catch(error => {
            console.error('Error changing mode:', error);
        });
}

// ===== UPDATE CONTROLS STATE =====
function updateControlsState() {
    const controlPad = document.getElementById('controlPad');
    const buttons = controlPad.querySelectorAll('.ctrl-btn');
    
    buttons.forEach(btn => {
        btn.disabled = isAutoMode;
    });
    
    if (isAutoMode) {
        controlPad.style.opacity = '0.4';
    } else {
        controlPad.style.opacity = '1';
    }
}

// ===== SPEED SLIDER =====
const speedSlider = document.getElementById('speedSlider');
const speedDisplay = document.getElementById('speedDisplay');

speedSlider.addEventListener('input', function() {
    speedDisplay.textContent = this.value;
});

speedSlider.addEventListener('change', function() {
    const speed = this.value;
    fetch('/set_speed?value=' + speed)
        .then(response => response.json())
        .then(data => {
            console.log('Speed set to:', speed, data);
            addLogEntry(new Date().toLocaleTimeString(), 'INFO', 
                'Speed adjusted to: ' + speed);
        })
        .catch(error => {
            console.error('Error setting speed:', error);
        });
});

// ===== KEYBOARD CONTROL =====
document.addEventListener('keydown', function(event) {
    // Không cho phép điều khiển bằng phím khi ở auto mode
    if (isAutoMode) {
        return;
    }
    
    switch(event.key) {
        case 'ArrowUp':
        case 'w':
        case 'W':
            sendCommand('forward');
            event.preventDefault();
            break;
        case 'ArrowDown':
        case 's':
        case 'S':
            sendCommand('backward');
            event.preventDefault();
            break;
        case 'ArrowLeft':
        case 'a':
        case 'A':
            sendCommand('left');
            event.preventDefault();
            break;
        case 'ArrowRight':
        case 'd':
        case 'D':
            sendCommand('right');
            event.preventDefault();
            break;
        case ' ':
            sendCommand('stop');
            event.preventDefault();
            break;
    }
});

// ===== LOG MANAGEMENT =====
function addLogEntry(time, level, message) {
    const logContent = document.getElementById('logContent');
    
    const entry = document.createElement('div');
    entry.className = 'log-entry log-' + level.toLowerCase();
    entry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-level">${level}</span>
        <span class="log-message">${message}</span>
    `;
    
    // Thêm vào đầu log
    logContent.insertBefore(entry, logContent.firstChild);
    
    // Giữ tối đa 50 entries
    while (logContent.children.length > 50) {
        logContent.removeChild(logContent.lastChild);
    }
}

function clearLog() {
    if (confirm('Clear all log entries?')) {
        fetch('/clear_log')
            .then(response => response.json())
            .then(data => {
                console.log('Log cleared:', data);
                document.getElementById('logContent').innerHTML = '';
                addLogEntry(new Date().toLocaleTimeString(), 'INFO', 
                    'Log cleared by user');
            })
            .catch(error => {
                console.error('Error clearing log:', error);
            });
    }
}

// ===== UPTIME COUNTER =====
function updateUptime() {
    const elapsed = Date.now() - startTime;
    const hours = Math.floor(elapsed / 3600000);
    const minutes = Math.floor((elapsed % 3600000) / 60000);
    
    document.getElementById('uptimeValue').textContent = 
        hours + 'h ' + minutes + 'm';
}

// Update uptime every minute
setInterval(updateUptime, 60000);

// ===== VIDEO STREAM ERROR HANDLING =====
document.getElementById('videoStream').addEventListener('error', function() {
    console.error('Error loading video stream');
    addLogEntry(new Date().toLocaleTimeString(), 'ERROR', 
        'Video stream connection lost');
});

// ===== INITIALIZATION =====
window.addEventListener('load', function() {
    console.log('Dashboard initialized');
    updateUptime();
    updateControlsState();
    
    // Initial log entry
    addLogEntry(new Date().toLocaleTimeString(), 'INFO', 
        'LogisticsBot Control Panel initialized');
});
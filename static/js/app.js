const socket = io();

// UI Elements
const autoSwitch = document.getElementById('autoModeSwitch');
const autoLabel = document.getElementById('autoModeLabel');
const stateValue = document.getElementById('stateValue');
const speedSlider = document.getElementById('speedSlider');
const speedDisplay = document.getElementById('speedDisplay');

// Socket Connection
socket.on('connect', () => {
    console.log("Socket connected!");
    updateConnection(true);
});

socket.on('disconnect', () => {
    console.log("Socket disconnected!");
    updateConnection(false);
});

function updateConnection(connected) {
    const badge = document.getElementById('connectionBadge');
    const text = document.getElementById('connectionText');
    if (connected) {
        badge.classList.remove('offline');
        text.textContent = 'Connected';
    } else {
        badge.classList.add('offline');
        text.textContent = 'Disconnected';
    }
}

// Toggle Auto Mode
function toggleAutoMode() {
    const isEnabled = autoSwitch.checked;
    autoLabel.textContent = isEnabled ? "ON" : "OFF";
    autoLabel.style.color = isEnabled ? "#4caf50" : "#666";
    
    // Send command to server
    // Server expects 'auto' to enable, 'manual' (or anything else) to disable/idle
    const mode = isEnabled ? 'auto' : 'manual'; 
    
    fetch(`/set_mode?mode=${mode}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => console.log('Mode set:', data))
        .catch(err => {
            console.error('Error setting mode:', err);
            // Revert switch if failed
            autoSwitch.checked = !isEnabled;
            autoLabel.textContent = !isEnabled ? "ON" : "OFF";
        });
}

// Speed Control
speedSlider.addEventListener('change', function() {
    const val = this.value;
    speedDisplay.textContent = val;
    fetch(`/set_speed?value=${val}`)
        .catch(err => console.error('Error setting speed:', err));
});

// Emergency Stop
function emergencyStop() {
    fetch('/emergency_stop')
        .catch(err => console.error('Error triggering emergency stop:', err));
    
    // Update UI immediately
    autoSwitch.checked = false;
    autoLabel.textContent = "OFF";
    stateValue.textContent = "EMERGENCY STOP";
    stateValue.style.color = "red";
}

// Reset Odometry
function resetOdometry() {
    fetch('/api/odometry/reset', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if(data.status === 'success') {
                console.log("Odometry reset successful");
            } else {
                console.error("Odometry reset failed:", data.error);
            }
        })
        .catch(err => console.error('Error resetting odometry:', err));
}

// Real-time Updates via Socket.IO
socket.on('sensor_update', (data) => {
    // State
    if (data.state) {
        stateValue.textContent = data.state;
        // Reset color if not emergency stop
        if (data.state !== 'EMERGENCY STOP') {
             stateValue.style.color = "#333"; 
        }
    }
    
    // Battery
    if(data.battery !== undefined) {
        const batteryBar = document.getElementById('batteryBar');
        if (batteryBar) batteryBar.style.width = data.battery + '%';
    }
    
    // Motors
    const motorElement = document.getElementById('motorValues');
    if (motorElement && data.left_motor_speed !== undefined && data.right_motor_speed !== undefined) {
        motorElement.textContent = `${data.left_motor_speed} / ${data.right_motor_speed}`;
    }
        
    // Sensors (Ultrasonic)
    const ultrasonicElement = document.getElementById('ultrasonicValue');
    if(ultrasonicElement && data.distance !== undefined) {
        ultrasonicElement.textContent = data.distance.toFixed(1) + ' cm';
    }
    
    // Sync Auto Switch UI with Server State
    // Check if auto mode was disabled externally (e.g. emergency stop from server or hardware)
    if(data.state === 'IDLE' || data.state === 'STOPPED' || data.state === 'EMERGENCY STOP') {
        if(autoSwitch.checked) {
            // Only uncheck if it's currently checked (to avoid loop)
            autoSwitch.checked = false;
            autoLabel.textContent = "OFF";
            autoLabel.style.color = "#666";
        }
    } else if (data.state === 'AUTO DRIVING') {
         if(!autoSwitch.checked) {
            autoSwitch.checked = true;
            autoLabel.textContent = "ON";
            autoLabel.style.color = "#4caf50";
        }
    }
});

// VO Updates (Separate polling)
// Poll every 500ms to avoid flooding the server
setInterval(async () => {
    try {
        const res = await fetch('/api/odometry/status');
        if (!res.ok) return; // Skip if server error (e.g. VO not ready)
        
        const data = await res.json();
        if(data.enabled) {
            const distElem = document.getElementById('vo-distance');
            const posXElem = document.getElementById('vo-pos-x');
            const posYElem = document.getElementById('vo-pos-y');

            if (distElem) distElem.textContent = data.distance_cm.toFixed(1) + ' cm';
            if (posXElem) posXElem.textContent = data.position.x_cm.toFixed(0);
            if (posYElem) posYElem.textContent = data.position.y_cm.toFixed(0);
        }
    } catch(e) {
        // Silent catch for network errors during polling
    }
}, 500);
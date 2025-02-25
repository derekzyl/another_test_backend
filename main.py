# from fastapi import status
# from fastapi.responses import JSONResponse

# from app.app import init_app, session_manager
# from app.core.auth.services.middleware_auth import AuthMiddleware
# from app.utils.crud.types_crud import response_message

# app = init_app()

# # app.add_middleware(AuthMiddleware, db_session=session_manager)


# # app.mount("/static", StaticFiles(directory="static"), name="static")
# # app.on_event("startup")

# @app.get('/')
# async def root():
#     return JSONResponse(status_code=status.HTTP_200_OK, content = response_message(data="welcome to smart home", success_status=True, message="success"))
#
import asyncio
import base64
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Set

import cloudinary
import cloudinary.uploader
import face_recognition
import numpy as np
from fastapi import (Depends, FastAPI, File, Form, HTTPException, UploadFile,
                     WebSocket, WebSocketDisconnect, status)
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey,
                        String, create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker
from sqlalchemy.sql import func

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "cybergenii"),
    api_key=os.getenv("CLOUDINARY_API_KEY", "148834358482124"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", "0pdvv7IpwYsCSZLH6NVOa9qAgi0"),
)


# Camera-related helper functions
def encode_face_encoding(face_encoding):
    """Convert numpy array to base64 string for storage"""
    return base64.b64encode(face_encoding.tobytes()).decode("utf-8")


def decode_face_encoding(encoded_string):
    """Convert base64 string back to numpy array"""
    decoded = base64.b64decode(encoded_string)
    return np.frombuffer(decoded, dtype=np.float64)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("smart-home-server")

# Initialize FastAPI app
app = FastAPI(title="Smart Home Server")
security = HTTPBasic()

# Database setup
SQLALCHEMY_DATABASE_URL = "postgresql://cybergenii:QMiHxYQRJQacIY9s8qoUprQVxiAvcs7y@dpg-cuumf5q3esus73aaekhg-a.oregon-postgres.render.com/hub_pq9z"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Models
class User(Base):
    __tablename__ = "users"

    id = Column(String(255), primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True)
    password = Column(String(255))  # Would be hashed in production
    full_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    hubs = relationship("Hub", back_populates="user")
    cameras = relationship("Camera", back_populates="user")
    family_members = relationship("FamilyMember", back_populates="user")

    def __init__(self, username, password, full_name):
        self.id = str(uuid.uuid4())
        self.username = username
        self.password = password
        self.full_name = full_name


class Hub(Base):
    __tablename__ = "hubs"

    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255))
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    alarm_state = Column(Boolean, default=False)
    online = Column(Boolean, default=False)

    # Foreign keys
    user_id = Column(String(255), ForeignKey("users.id"))

    # Relationships
    user = relationship("User", back_populates="hubs")
    devices = relationship("Device", back_populates="hub", cascade="all, delete-orphan")
    cameras = relationship("Camera", back_populates="hub")
    def __init__(self, id, name, user_id):
        self.id = id
        self.name = name
        self.user_id = user_id


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255))
    device_type = Column(String(255))
    status = Column(String(255), default="Unknown")
    last_updated = Column(DateTime, default=datetime.utcnow)

    # Foreign keys
    hub_id = Column(String(255), ForeignKey("hubs.id"))

    # Relationships
    hub = relationship("Hub", back_populates="devices")

    def __init__(self, id, name, device_type, hub_id):
        self.id = id
        self.name = name
        self.device_type = device_type
        self.hub_id = hub_id


# Database Models for Camera Integration
class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255))
    is_online = Column(Boolean, default=True)
    last_motion = Column(DateTime, nullable=True)
    last_image_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Foreign keys
    hub_id = Column(String(255), ForeignKey("hubs.id"))
    user_id = Column(String(255), ForeignKey("users.id"))

    # Relationships
    hub = relationship("Hub", back_populates="cameras")
    user = relationship("User", back_populates="cameras")
    family_members = relationship("CameraFamilyMember", back_populates="camera")

    def __init__(self, id, name, hub_id, user_id):
        self.id = id
        self.name = name
        self.hub_id = hub_id
        self.user_id = user_id


class FamilyMember(Base):
    __tablename__ = "family_members"

    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255))
    image_url = Column(String(512))
    face_encoding = Column(String(4096))  # Store as base64 encoded string
    created_at = Column(DateTime, default=datetime.utcnow)

    # Foreign key
    user_id = Column(String(255), ForeignKey("users.id"))

    # Relationships
    user = relationship("User", back_populates="family_members")
    cameras = relationship("CameraFamilyMember", back_populates="family_member")

    def __init__(self, id, name, image_url, face_encoding, user_id):
        self.id = id
        self.name = name
        self.image_url = image_url
        self.face_encoding = face_encoding
        self.user_id = user_id


class CameraFamilyMember(Base):
    __tablename__ = "camera_family_members"

    camera_id = Column(String(255), ForeignKey("cameras.id"), primary_key=True)
    family_member_id = Column(
        String(255), ForeignKey("family_members.id"), primary_key=True
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    camera = relationship("Camera", back_populates="family_members")
    family_member = relationship("FamilyMember", back_populates="cameras")


# Create tables
Base.metadata.create_all(bind=engine)


# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Initialize with a default user
def create_default_user():
    db = SessionLocal()
    try:
        # Check if default user exists
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            default_user = User(
                username="admin",
                password="password123",  # This would be hashed in production
                full_name="Administrator",
            )
            db.add(default_user)
            db.commit()
            logger.info("Default user created")
    except Exception as e:
        logger.error(f"Error creating default user: {e}")
    finally:
        db.close()


create_default_user()


# Authentication functions
def verify_credentials(credentials: HTTPBasicCredentials, db: Session):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user:
        return False

    correct_password = user.password
    is_correct = secrets.compare_digest(credentials.password, correct_password)

    return is_correct, user


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)
):
    is_authenticated, user = verify_credentials(credentials, db)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def authenticate_hub(hub_id: str, username: str, password: str, db: Session) -> bool:
    # Check if user exists and password matches
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return False, None

    is_correct = secrets.compare_digest(password, user.password)
    if is_correct:
        # Find or create hub
        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if not hub:
            hub = Hub(id=hub_id, name=f"Hub {hub_id[-6:]}", user_id=user.id)
            db.add(hub)
            db.commit()

        return True, user.id

    return False, None


# Connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, hub_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[hub_id] = websocket
        logger.info(f"Hub {hub_id} connected")

    def disconnect(self, hub_id: str):
        if hub_id in self.active_connections:
            del self.active_connections[hub_id]
            logger.info(f"Hub {hub_id} disconnected")

    async def send_message(self, hub_id: str, message: str):
        if hub_id in self.active_connections:
            try:
                await self.active_connections[hub_id].send_text(message)
                return True
            except Exception as e:
                logger.error(f"Error sending message to hub {hub_id}: {e}")
                return False
        return False

    async def broadcast(self, message: str):
        for hub_id, connection in self.active_connections.items():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to hub {hub_id}: {e}")


# Initialize connection manager
manager = ConnectionManager()


# WebSocket endpoint for hubs
@app.websocket("/ws/hub/{hub_id}")
async def websocket_endpoint(
    websocket: WebSocket, hub_id: str, db: Session = Depends(get_db)
):
    await manager.connect(hub_id, websocket)
    try:
        # Mark hub as online
        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub:
            hub.online = True
            db.commit()

        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await process_hub_message(hub_id, message, websocket, db)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from hub {hub_id}: {data}")
    except WebSocketDisconnect:
        manager.disconnect(hub_id)
        # Mark hub as offline
        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub:
            hub.online = False
            db.commit()


async def process_hub_message(
    hub_id: str, message: dict, websocket: WebSocket, db: Session
):
    msg_type = message.get("type")

    # Process based on message type
    if msg_type == "auth":
        # Handle authentication
        username = message.get("username", "")
        password = message.get("password", "")
        auth_success, user_id = authenticate_hub(hub_id, username, password, db)

        if auth_success:
            response = {
                "type": "auth_response",
                "success": True,
                "message": "Authentication successful",
            }
            logger.info(f"Hub {hub_id} authenticated successfully")
        else:
            response = {
                "type": "auth_response",
                "success": False,
                "message": "Authentication failed",
            }
            logger.warning(f"Auth failed for hub {hub_id}")

        await websocket.send_text(json.dumps(response))

    elif msg_type == "heartbeat":
        # Update last heartbeat time
        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub:
            hub.last_heartbeat = datetime.utcnow()
            db.commit()
            logger.debug(f"Received heartbeat from hub {hub_id}")

    elif msg_type == "hub_status":
        # Update hub status
        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub:
            hub.temperature = message.get("temperature")
            hub.humidity = message.get("humidity")
            hub.alarm_state = message.get("alarmState", False)
            db.commit()

            # Update devices
            devices = message.get("devices", [])

            for device_data in devices:
                device_id = device_data.get("id")
                if device_id:
                    device = db.query(Device).filter(Device.id == device_id).first()
                    if not device:
                        device = Device(
                            id=device_id,
                            name=device_data.get("name", f"Device {device_id[-6:]}"),
                            device_type=device_data.get("type", "unknown"),
                            hub_id=hub_id,
                        )
                        db.add(device)

                    device.status = device_data.get("status", "Unknown")
                    device.last_updated = datetime.utcnow()

            db.commit()
            logger.info(f"Updated status for hub {hub_id}")

    elif msg_type == "device_added":
        # Register new device
        device_id = message.get("deviceId")
        device_type = message.get("deviceType")
        device_name = message.get("deviceName", f"Device {device_id[-6:]}")

        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub and device_id:
            device = db.query(Device).filter(Device.id == device_id).first()
            if not device:
                device = Device(
                    id=device_id,
                    name=device_name,
                    device_type=device_type or "unknown",
                    hub_id=hub_id,
                )
                db.add(device)
                db.commit()
                logger.info(f"New device {device_id} added to hub {hub_id}")

    elif msg_type == "device_status":
        # Update device status
        device_id = message.get("deviceId")
        status = message.get("status")

        device = (
            db.query(Device)
            .filter(Device.id == device_id, Device.hub_id == hub_id)
            .first()
        )
        if device:
            device.status = status
            device.last_updated = datetime.utcnow()
            db.commit()
            logger.info(
                f"Updated status for device {device_id} on hub {hub_id}: {status}"
            )

    elif msg_type == "alert":
        # Handle device alerts (e.g., smoke detector)
        device_id = message.get("deviceId")
        alert_type = message.get("alertType")

        logger.warning(f"ALERT from device {device_id} on hub {hub_id}: {alert_type}")

        # In a real system, you might trigger notifications to users here


# API Endpoints - Simplified for user interaction
@app.get("/api/user/hubs", response_model=List[Dict])
async def get_user_hubs(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    hubs = db.query(Hub).filter(Hub.user_id == current_user.id).all()
    return [
        {
            "hub_id": hub.id,
            "name": hub.name,
            "connected_at": hub.connected_at.isoformat() if hub.connected_at else None,
            "last_heartbeat": (
                hub.last_heartbeat.isoformat() if hub.last_heartbeat else None
            ),
            "temperature": hub.temperature,
            "humidity": hub.humidity,
            "alarm_state": hub.alarm_state,
            "online": hub.online,
        }
        for hub in hubs
    ]


@app.get("/api/user/hubs/{hub_id}", response_model=Dict)
async def get_user_hub(
    hub_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hub = db.query(Hub).filter(Hub.id == hub_id, Hub.user_id == current_user.id).first()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    devices = db.query(Device).filter(Device.hub_id == hub_id).all()
    return {
        "hub_id": hub.id,
        "name": hub.name,
        "connected_at": hub.connected_at.isoformat() if hub.connected_at else None,
        "last_heartbeat": (
            hub.last_heartbeat.isoformat() if hub.last_heartbeat else None
        ),
        "temperature": hub.temperature,
        "humidity": hub.humidity,
        "alarm_state": hub.alarm_state,
        "online": hub.online,
        "devices": [
            {
                "device_id": device.id,
                "name": device.name,
                "type": device.device_type,
                "status": device.status,
                "last_updated": (
                    device.last_updated.isoformat() if device.last_updated else None
                ),
            }
            for device in devices
        ],
    }


@app.post("/api/user/hubs/{hub_id}/control/{device_id}")
async def control_device(
    hub_id: str,
    device_id: str,
    command: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hub = db.query(Hub).filter(Hub.id == hub_id, Hub.user_id == current_user.id).first()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    if not hub.online:
        raise HTTPException(status_code=503, detail="Hub is offline")

    device = (
        db.query(Device).filter(Device.id == device_id, Device.hub_id == hub_id).first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Send control command to hub
    message = {"type": "control", "deviceId": device_id, "command": command}

    success = await manager.send_message(hub_id, json.dumps(message))
    if success:
        return {
            "status": "success",
            "message": f"Command {command} sent to device {device_id}",
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to send command to hub")


@app.post("/api/user/hubs/{hub_id}/alarm")
async def control_alarm(
    hub_id: str,
    state: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hub = db.query(Hub).filter(Hub.id == hub_id, Hub.user_id == current_user.id).first()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    if not hub.online:
        raise HTTPException(status_code=503, detail="Hub is offline")

    # Send alarm control command to hub
    message = {"type": "alarm", "state": state}

    success = await manager.send_message(hub_id, json.dumps(message))
    if success:
        # Update database state
        hub.alarm_state = state
        db.commit()
        return {
            "status": "success",
            "message": f"Alarm {'activated' if state else 'deactivated'}",
        }
    else:
        raise HTTPException(
            status_code=500, detail="Failed to send alarm command to hub"
        )


# Simple dashboard HTML - Updated for user interaction
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(current_user: User = Depends(get_current_user)):
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>My Smart Home</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; }
            .hub-card { margin-bottom: 20px; }
            .device-card { margin: 10px 0; }
            .offline { opacity: 0.5; }
        </style>
        <script>
            // Fetch user's hubs every 5 seconds
            async function fetchHubs() {
                try {
                    const response = await fetch('/api/user/hubs');
                    if (response.ok) {
                        const hubs = await response.json();
                        const hubsContainer = document.getElementById('hubs-container');
                        hubsContainer.innerHTML = '';
                        
                        if (hubs.length === 0) {
                            hubsContainer.innerHTML = '<div class="alert alert-info">No hubs found. Please connect a hub to your account.</div>';
                            return;
                        }
                        
                        for (const hub of hubs) {
                            const hubElement = createHubElement(hub);
                            hubsContainer.appendChild(hubElement);
                            
                            // Fetch devices for this hub
                            fetchDevices(hub.hub_id);
                        }
                    } else {
                        console.error('Failed to fetch hubs:', response.statusText);
                    }
                } catch (error) {
                    console.error('Error fetching hubs:', error);
                }
                
                // Schedule next update
                setTimeout(fetchHubs, 5000);
            }
            
            async function fetchDevices(hubId) {
                try {
                    const response = await fetch(`/api/user/hubs/${hubId}`);
                    if (response.ok) {
                        const hubData = await response.json();
                        const devicesContainer = document.getElementById(`devices-${hubId}`);
                        devicesContainer.innerHTML = '';
                        
                        if (hubData.devices.length === 0) {
                            devicesContainer.innerHTML = '<div class="alert alert-info">No devices connected to this hub yet.</div>';
                            return;
                        }
                        
                        for (const device of hubData.devices) {
                            const deviceElement = createDeviceElement(hubId, device);
                            devicesContainer.appendChild(deviceElement);
                        }
                    } else {
                        console.error(`Failed to fetch devices for hub ${hubId}:`, response.statusText);
                    }
                } catch (error) {
                    console.error(`Error fetching devices for hub ${hubId}:`, error);
                }
            }
            
            function createHubElement(hub) {
                const hubCard = document.createElement('div');
                hubCard.className = `card hub-card ${hub.online ? '' : 'offline'}`;
                
                const hubBody = document.createElement('div');
                hubBody.className = 'card-body';
                
                const hubTitle = document.createElement('h5');
                hubTitle.className = 'card-title';
                hubTitle.textContent = `${hub.name} ${hub.online ? '(Online)' : '(Offline)'}`;
                
                const hubDetails = document.createElement('div');
                hubDetails.innerHTML = `
                    <p>Temperature: ${hub.temperature !== null ? hub.temperature + '°C' : 'N/A'}</p>
                    <p>Humidity: ${hub.humidity !== null ? hub.humidity + '%' : 'N/A'}</p>
                    <p>Alarm: ${hub.alarm_state ? 'ON' : 'OFF'}</p>
                `;
                
                const alarmControls = document.createElement('div');
                alarmControls.className = 'mb-3';
                alarmControls.innerHTML = `
                    <button class="btn btn-success" onclick="controlAlarm('${hub.hub_id}', false)" ${!hub.online ? 'disabled' : ''}>Alarm OFF</button>
                    <button class="btn btn-danger" onclick="controlAlarm('${hub.hub_id}', true)" ${!hub.online ? 'disabled' : ''}>Alarm ON</button>
                `;
                
                const devicesContainer = document.createElement('div');
                devicesContainer.id = `devices-${hub.hub_id}`;
                devicesContainer.className = 'mt-3';
                
                hubBody.appendChild(hubTitle);
                hubBody.appendChild(hubDetails);
                hubBody.appendChild(alarmControls);
                hubBody.appendChild(document.createElement('hr'));
                hubBody.appendChild(document.createElement('h6')).textContent = 'Devices:';
                hubBody.appendChild(devicesContainer);
                hubCard.appendChild(hubBody);
                
                return hubCard;
            }
            
            function createDeviceElement(hubId, device) {
                const deviceCard = document.createElement('div');
                deviceCard.className = 'card device-card';
                
                const deviceBody = document.createElement('div');
                deviceBody.className = 'card-body';
                
                const deviceTitle = document.createElement('div');
                deviceTitle.className = 'd-flex justify-content-between align-items-center';
                deviceTitle.innerHTML = `
                    <h6 class="card-title mb-0">${device.name} (${device.type})</h6>
                    <span class="badge bg-${getStatusColor(device.status)}">${device.status}</span>
                `;
                
                const deviceControls = document.createElement('div');
                deviceControls.className = 'mt-2';
                
                // Add appropriate controls based on device type
                if (device.type === 'smart_switch' || device.type === 'smart_bulb') {
                    deviceControls.innerHTML = `
                        <button class="btn btn-sm btn-success" onclick="controlDevice('${hubId}', '${device.device_id}', 'on')">On</button>
                        <button class="btn btn-sm btn-danger" onclick="controlDevice('${hubId}', '${device.device_id}', 'off')">Off</button>
                    `;
                } else if (device.type === 'window_blind') {
                    deviceControls.innerHTML = `
                        <button class="btn btn-sm btn-primary" onclick="controlDevice('${hubId}', '${device.device_id}', 'up')">Up</button>
                        <button class="btn btn-sm btn-warning" onclick="controlDevice('${hubId}', '${device.device_id}', 'stop')">Stop</button>
                        <button class="btn btn-sm btn-primary" onclick="controlDevice('${hubId}', '${device.device_id}', 'down')">Down</button>
                    `;
                } else if (device.type === 'smoke_sensor') {
                    deviceControls.innerHTML = `
                        <button class="btn btn-sm btn-info" onclick="controlDevice('${hubId}', '${device.device_id}', 'get_status')">Refresh</button>
                    `;
                } else {
                    deviceControls.innerHTML = `
                        <button class="btn btn-sm btn-info" onclick="controlDevice('${hubId}', '${device.device_id}', 'get_status')">Get Status</button>
                    `;
                }
                
                deviceBody.appendChild(deviceTitle);
                deviceBody.appendChild(deviceControls);
                deviceCard.appendChild(deviceBody);
                
                return deviceCard;
            }
            
            function getStatusColor(status) {
                switch (status.toLowerCase()) {
                    case 'on':
                        return 'success';
                    case 'off':
                        return 'danger';
                    case 'error':
                        return 'danger';
                    case 'unknown':
                        return 'secondary';
                    default:
                        return 'primary';
                }
            }
            
            async function controlDevice(hubId, deviceId, command) {
                try {
                    const response = await fetch(`/api/user/hubs/${hubId}/control/${deviceId}?command=${command}`, {
                        method: 'POST',
                    });
                    
                    if (response.ok) {
                        const result = await response.json();
                        // Simple notification
                        showNotification(result.message);
                        // Refresh devices to show the new state
                        setTimeout(() => fetchDevices(hubId), 1000);
                    } else {
                        const errorData = await response.json();
                        showNotification(`Error: ${errorData.detail}`, true);
                    }
                } catch (error) {
                    console.error('Error controlling device:', error);
                    showNotification('Error controlling device', true);
                }
            }
            
            async function controlAlarm(hubId, state) {
                try {
                    const response = await fetch(`/api/user/hubs/${hubId}/alarm?state=${state}`, {
                        method: 'POST',
                    });
                    
                    if (response.ok) {
                        const result = await response.json();
                        // Simple notification
                        showNotification(result.message);
                        // Refresh hubs to show the new alarm state
                        setTimeout(fetchHubs, 1000);
                    } else {
                        const errorData = await response.json();
                        showNotification(`Error: ${errorData.detail}`, true);
                    }
                } catch (error) {
                    console.error('Error controlling alarm:', error);
                    showNotification('Error controlling alarm', true);
                }
            }
            
            function showNotification(message, isError = false) {
                const notifContainer = document.getElementById('notification-container');
                const notif = document.createElement('div');
                notif.className = `alert alert-${isError ? 'danger' : 'success'} alert-dismissible fade show`;
                notif.innerHTML = `
                    ${message}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                `;
                notifContainer.appendChild(notif);
                
                // Auto-dismiss after 3 seconds
                setTimeout(() => {
                    notif.classList.remove('show');
                    setTimeout(() => {
                        notifContainer.removeChild(notif);
                    }, 150);
                }, 3000);
            }
            
            // Start fetching data when page loads
            document.addEventListener('DOMContentLoaded', fetchHubs);
        </script>
    </head>
    <body>
        <div class="container">
            <h1 class="mb-4">My Smart Home</h1>
            <div id="notification-container" class="position-fixed top-0 end-0 p-3" style="z-index: 1050;"></div>
            <div id="hubs-container"></div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return html_content


# Periodic tasks
async def update_hub_statuses():
    """Update hub online status and handle inactive hubs"""
    while True:
        try:
            db = SessionLocal()
            current_time = datetime.utcnow()

            # Get all hubs
            hubs = db.query(Hub).all()

            for hub in hubs:
                # Check if hub has been inactive for more than 2 minutes
                if (
                    current_time - hub.last_heartbeat
                ).total_seconds() > 120:  # 2 minutes
                    hub.online = False

            db.commit()
        except Exception as e:
            logger.error(f"Error in update_hub_statuses: {e}")
        finally:
            db.close()

        await asyncio.sleep(60)  # Check every minute

#  Camera-related endpoints
@app.post("/api/camera/register")
async def register_camera(
    camera_id: str = Form(...),
    camera_name: str = Form(...),
    hub_id: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a new camera device"""
    # Check if camera already exists
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera:
        raise HTTPException(status_code=400, detail="Camera already registered")

    # Check if hub exists and belongs to the user
    hub = db.query(Hub).filter(Hub.id == hub_id, Hub.user_id == current_user.id).first()
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found or not authorized")

    # Create new camera
    new_camera = Camera(
        id=camera_id, name=camera_name, hub_id=hub_id, user_id=current_user.id
    )
    db.add(new_camera)
    db.commit()

    logger.info(f"New camera registered: {camera_id} on hub {hub_id}")
    return {"status": "success", "message": "Camera registered successfully"}


@app.post("/api/camera/upload")
async def upload_image(
    file: UploadFile = File(...),
    camera_id: str = Form(...),
    hub_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Handle image upload from camera when motion is detected"""
    # Check if camera exists
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not registered")

    # Check if camera belongs to the provided hub
    if camera.hub_id != hub_id:
        raise HTTPException(
            status_code=403, detail="Camera does not belong to this hub"
        )

    try:
        # Read image content
        contents = await file.read()
        image = Image.open(BytesIO(contents))

        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(contents)
        image_url = upload_result["secure_url"]

        # Process image for face recognition
        np_image = np.array(image)
        face_locations = face_recognition.face_locations(np_image)
        recognized_names = []
        unknown_detected = False

        if face_locations:
            # Get face encodings
            face_encodings = face_recognition.face_encodings(np_image, face_locations)

            # Get family members associated with this camera
            camera_family_members = (
                db.query(CameraFamilyMember, FamilyMember)
                .join(
                    FamilyMember, CameraFamilyMember.family_member_id == FamilyMember.id
                )
                .filter(CameraFamilyMember.camera_id == camera_id)
                .all()
            )

            # Compare with known family members
            for face_encoding in face_encodings:
                matched = False
                for _, family_member in camera_family_members:
                    known_encoding = decode_face_encoding(family_member.face_encoding)
                    # Compare faces
                    if face_recognition.compare_faces([known_encoding], face_encoding)[
                        0
                    ]:
                        recognized_names.append(family_member.name)
                        matched = True
                        break

                if not matched:
                    unknown_detected = True

        # Update camera status
        camera.last_motion = datetime.utcnow()
        camera.last_image_url = image_url
        db.commit()

        # If unknown person detected, send alert to user through the hub
        if unknown_detected:
            logger.warning(f"Unknown person detected by camera {camera_id}")
            await send_camera_alert(
                hub_id, camera_id, "Unknown person detected", image_url, db
            )
        elif recognized_names:
            logger.info(
                f"Known persons detected by camera {camera_id}: {', '.join(recognized_names)}"
            )

        return {
            "status": "success",
            "image_url": image_url,
            "recognized": len(recognized_names) > 0,
            "recognized_names": recognized_names if recognized_names else [],
            "unknown_detected": unknown_detected,
        }

    except Exception as e:
        logger.error(f"Error processing camera upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/family/add")
async def add_family_member(
    name: str = Form(...),
    camera_ids: str = Form(...),  # Comma-separated list of camera IDs
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new family member with facial recognition"""
    try:
        # Read and process the image
        contents = await image.read()
        image_pil = Image.open(BytesIO(contents))
        np_image = np.array(image_pil)

        # Detect faces
        face_locations = face_recognition.face_locations(np_image)
        if not face_locations:
            raise HTTPException(status_code=400, detail="No face detected in image")

        # Get face encoding
        face_encodings = face_recognition.face_encodings(np_image, face_locations)
        if not face_encodings:
            raise HTTPException(status_code=400, detail="Could not encode face")

        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(contents)
        image_url = upload_result["secure_url"]

        # Create family member record
        member_id = str(uuid.uuid4())
        encoded_face = encode_face_encoding(face_encodings[0])

        new_family_member = FamilyMember(
            id=member_id,
            name=name,
            image_url=image_url,
            face_encoding=encoded_face,
            user_id=current_user.id,
        )
        db.add(new_family_member)

        # Associate with cameras
        camera_id_list = [cid.strip() for cid in camera_ids.split(",")]

        for camera_id in camera_id_list:
            # Check if camera exists and belongs to user
            camera = (
                db.query(Camera)
                .filter(Camera.id == camera_id, Camera.user_id == current_user.id)
                .first()
            )

            if camera:
                camera_family = CameraFamilyMember()
                camera_family.camera_id = camera_id
                camera_family.family_member_id = member_id
                db.add(camera_family)

        db.commit()

        return {
            "status": "success",
            "member_id": member_id,
            "name": name,
            "image_url": image_url,
        }

    except Exception as e:
        logger.error(f"Error adding family member: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/camera/{camera_id}/status")
async def get_camera_status(
    camera_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current status of a camera"""
    # Check if camera exists and belongs to user
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.user_id == current_user.id)
        .first()
    )

    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Get family members associated with this camera
    family_members = (
        db.query(FamilyMember)
        .join(CameraFamilyMember)
        .filter(CameraFamilyMember.camera_id == camera_id)
        .all()
    )

    return {
        "camera_id": camera.id,
        "name": camera.name,
        "is_online": camera.is_online,
        "last_motion": camera.last_motion.isoformat() if camera.last_motion else None,
        "last_image_url": camera.last_image_url,
        "hub_id": camera.hub_id,
        "family_members": [
            {"member_id": member.id, "name": member.name, "image_url": member.image_url}
            for member in family_members
        ],
    }


@app.get("/api/user/cameras")
async def get_user_cameras(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get all cameras for the current user"""
    cameras = db.query(Camera).filter(Camera.user_id == current_user.id).all()

    return [
        {
            "camera_id": camera.id,
            "name": camera.name,
            "is_online": camera.is_online,
            "last_motion": (
                camera.last_motion.isoformat() if camera.last_motion else None
            ),
            "hub_id": camera.hub_id,
            "hub_name": camera.hub.name if camera.hub else None,
        }
        for camera in cameras
    ]


@app.get("/api/user/family")
async def get_family_members(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get all family members for the current user"""
    family_members = (
        db.query(FamilyMember).filter(FamilyMember.user_id == current_user.id).all()
    )

    return [
        {
            "member_id": member.id,
            "name": member.name,
            "image_url": member.image_url,
            "cameras": [
                {
                    "camera_id": association.camera_id,
                    "camera_name": association.camera.name,
                }
                for association in member.cameras
            ],
        }
        for member in family_members
    ]


async def send_camera_alert(
    hub_id: str, camera_id: str, message: str, image_url: str, db: Session
):
    """Send notification to user about camera alert"""
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        return

    # Find hub and check if it's online
    hub = db.query(Hub).filter(Hub.id == hub_id).first()
    if not hub or not hub.online:
        logger.warning(f"Cannot send alert: Hub {hub_id} is offline or not found")
        return

    alert_message = {
        "type": "camera_alert",
        "camera_id": camera_id,
        "camera_name": camera.name,
        "message": message,
        "image_url": image_url,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Send to hub via WebSocket
    await manager.send_message(hub_id, json.dumps(alert_message))


async def check_camera_status():
    """Check and update camera online status"""
    while True:
        try:
            db = SessionLocal()
            cameras = db.query(Camera).all()
            current_time = datetime.utcnow()

            for camera in cameras:
                # Mark camera as offline if no activity for 5 minutes
                if (
                    camera.last_motion
                    and (current_time - camera.last_motion).total_seconds() > 300
                ):  # 5 minutes
                    if camera.is_online:  # Only log if status changes
                        logger.warning(f"Camera {camera.id} appears to be offline")
                    camera.is_online = False
                    db.commit()

        except Exception as e:
            logger.error(f"Error in check_camera_status: {e}")
        finally:
            db.close()

        await asyncio.sleep(60)  # Check every minute


# Extend process_hub_message to handle camera-related messages
async def process_hub_message(
    hub_id: str, message: dict, websocket: WebSocket, db: Session
):
    msg_type = message.get("type")

    # Add camera handling to the existing message processing
    if msg_type == "camera_added":
        # Register new camera from hub
        camera_id = message.get("cameraId")
        camera_name = message.get("cameraName", f"Camera {camera_id[-6:]}")

        hub = db.query(Hub).filter(Hub.id == hub_id).first()
        if hub and camera_id:
            camera = db.query(Camera).filter(Camera.id == camera_id).first()
            if not camera:
                camera = Camera(
                    id=camera_id, name=camera_name, hub_id=hub_id, user_id=hub.user_id
                )
                db.add(camera)
                db.commit()
                logger.info(f"New camera {camera_id} added to hub {hub_id}")

                # Send confirmation to hub
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "camera_registered",
                            "cameraId": camera_id,
                            "success": True,
                        }
                    )
                )
            else:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "camera_registered",
                            "cameraId": camera_id,
                            "success": False,
                            "error": "Camera already registered",
                        }
                    )
                )

    elif msg_type == "camera_status":
        # Update camera status
        camera_id = message.get("cameraId")
        is_online = message.get("online", True)

        camera = (
            db.query(Camera)
            .filter(Camera.id == camera_id, Camera.hub_id == hub_id)
            .first()
        )
        if camera:
            camera.is_online = is_online
            db.commit()
            logger.info(
                f"Updated status for camera {camera_id} on hub {hub_id}: {'online' if is_online else 'offline'}"
            )

    # Process other message types (from the existing code)
    else:
        # Existing message handling code goes here
        pass  # This should be replaced with the original code


# Update the startup event to include camera status check
@app.on_event("startup")
async def startup_events():
    # Start background tasks
    asyncio.create_task(update_hub_statuses())
    asyncio.create_task(check_camera_status())



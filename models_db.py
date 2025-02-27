
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


from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid
import json

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    user_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # Nullable for OAuth users
    google_id = db.Column(db.String(100), unique=True, nullable=True)  # For Gmail OAuth
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    preferences = db.Column(db.Text, nullable=True)  # JSON string
    
    # Profile information
    full_name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    gate_exam_year = db.Column(db.String(4), nullable=True)
    target_score = db.Column(db.Integer, nullable=True)
    previous_attempts = db.Column(db.Boolean, default=False)
    
    # Relationships
    study_plans = db.relationship('StudyPlan', backref='user', lazy=True, cascade='all, delete-orphan')
    progress_records = db.relationship('UserProgress', backref='user', lazy=True, cascade='all, delete-orphan')
    flashcard_sets = db.relationship('FlashcardSet', backref='user', lazy=True, cascade='all, delete-orphan')
    mock_test_attempts = db.relationship('MockTestAttempt', backref='user', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.username}>'

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'phone': self.phone,
            'gate_exam_year': self.gate_exam_year,
            'target_score': self.target_score,
            'previous_attempts': self.previous_attempts,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'preferences': json.loads(self.preferences) if self.preferences else {}
        }

class Syllabus(db.Model):
    __tablename__ = 'syllabi'
    
    syllabus_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    discipline = db.Column(db.String(100), nullable=False)
    gate_year = db.Column(db.String(4), nullable=False)
    description = db.Column(db.Text, nullable=True)
    raw_content = db.Column(db.Text, nullable=True)  # JSON string
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=True)
    
    # Relationships
    topics = db.relationship('Topic', backref='syllabus', lazy=True, cascade='all, delete-orphan')
    study_plans = db.relationship('StudyPlan', backref='syllabus', lazy=True)

    def to_dict(self):
        return {
            'syllabus_id': self.syllabus_id,
            'discipline': self.discipline,
            'gate_year': self.gate_year,
            'description': self.description,
            'raw_content': json.loads(self.raw_content) if self.raw_content else {},
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'uploaded_by': self.uploaded_by
        }

class Topic(db.Model):
    __tablename__ = 'topics'
    
    topic_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    syllabus_id = db.Column(db.String(36), db.ForeignKey('syllabi.syllabus_id'), nullable=False)
    topic_name = db.Column(db.String(200), nullable=False)
    topic_description = db.Column(db.Text, nullable=True)
    estimated_hours = db.Column(db.Integer, nullable=True)
    topic_metadata = db.Column(db.Text, nullable=True)  # JSON string
    
    # Relationships
    subtopics = db.relationship('Subtopic', backref='topic', lazy=True, cascade='all, delete-orphan')
    study_plan_items = db.relationship('StudyPlanItem', backref='topic', lazy=True)
    progress_records = db.relationship('UserProgress', backref='topic', lazy=True)
    question_patterns = db.relationship('QuestionPattern', backref='topic', lazy=True)

    def to_dict(self):
        return {
            'topic_id': self.topic_id,
            'syllabus_id': self.syllabus_id,
            'topic_name': self.topic_name,
            'topic_description': self.topic_description,
            'estimated_hours': self.estimated_hours,
            'metadata': json.loads(self.topic_metadata) if self.topic_metadata else {}
        }

class Subtopic(db.Model):
    __tablename__ = 'subtopics'
    
    subtopic_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = db.Column(db.String(36), db.ForeignKey('topics.topic_id'), nullable=False)
    subtopic_name = db.Column(db.String(200), nullable=False)
    subtopic_description = db.Column(db.Text, nullable=True)
    estimated_hours = db.Column(db.Integer, nullable=True)

    def to_dict(self):
        return {
            'subtopic_id': self.subtopic_id,
            'topic_id': self.topic_id,
            'subtopic_name': self.subtopic_name,
            'subtopic_description': self.subtopic_description,
            'estimated_hours': self.estimated_hours
        }

class StudyPlan(db.Model):
    __tablename__ = 'study_plans'
    
    plan_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False)
    syllabus_id = db.Column(db.String(36), db.ForeignKey('syllabi.syllabus_id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    plan_status = db.Column(db.String(20), default='generated')  # generated, active, completed, archived
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    plan_details = db.Column(db.Text, nullable=True)  # JSON string
    
    # Relationships
    study_plan_items = db.relationship('StudyPlanItem', backref='study_plan', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'plan_id': self.plan_id,
            'user_id': self.user_id,
            'syllabus_id': self.syllabus_id,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'plan_status': self.plan_status,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'plan_details': json.loads(self.plan_details) if self.plan_details else {}
        }

class StudyPlanItem(db.Model):
    __tablename__ = 'study_plan_items'
    
    item_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = db.Column(db.String(36), db.ForeignKey('study_plans.plan_id'), nullable=False)
    topic_id = db.Column(db.String(36), db.ForeignKey('topics.topic_id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_hours = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, in_progress, completed, skipped
    notes = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'item_id': self.item_id,
            'plan_id': self.plan_id,
            'topic_id': self.topic_id,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'scheduled_hours': self.scheduled_hours,
            'status': self.status,
            'notes': self.notes
        }

class UserProgress(db.Model):
    __tablename__ = 'user_progress'
    
    progress_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False)
    topic_id = db.Column(db.String(36), db.ForeignKey('topics.topic_id'), nullable=False)
    progress_date = db.Column(db.Date, nullable=False)
    hours_studied = db.Column(db.Integer, nullable=False)
    mastery_score = db.Column(db.Float, nullable=True)  # 0-100
    performance_data = db.Column(db.Text, nullable=True)  # JSON string

    def to_dict(self):
        return {
            'progress_id': self.progress_id,
            'user_id': self.user_id,
            'topic_id': self.topic_id,
            'progress_date': self.progress_date.isoformat() if self.progress_date else None,
            'hours_studied': self.hours_studied,
            'mastery_score': self.mastery_score,
            'performance_data': json.loads(self.performance_data) if self.performance_data else {}
        }

class FlashcardSet(db.Model):
    __tablename__ = 'flashcard_sets'
    
    set_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False)
    set_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    flashcards = db.relationship('Flashcard', backref='flashcard_set', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'set_id': self.set_id,
            'user_id': self.user_id,
            'set_name': self.set_name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Flashcard(db.Model):
    __tablename__ = 'flashcards'
    
    card_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    set_id = db.Column(db.String(36), db.ForeignKey('flashcard_sets.set_id'), nullable=False)
    front_content = db.Column(db.Text, nullable=False)
    back_content = db.Column(db.Text, nullable=False)
    next_review_date = db.Column(db.Date, nullable=True)
    repetition_level = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'card_id': self.card_id,
            'set_id': self.set_id,
            'front_content': self.front_content,
            'back_content': self.back_content,
            'next_review_date': self.next_review_date.isoformat() if self.next_review_date else None,
            'repetition_level': self.repetition_level
        }

class MockTestAttempt(db.Model):
    __tablename__ = 'mock_test_attempts'
    
    attempt_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False)
    mock_test_id = db.Column(db.String(36), nullable=False)  # Reference to mock test
    attempt_time = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float, nullable=False)
    detailed_results = db.Column(db.Text, nullable=True)  # JSON string

    def to_dict(self):
        return {
            'attempt_id': self.attempt_id,
            'user_id': self.user_id,
            'mock_test_id': self.mock_test_id,
            'attempt_time': self.attempt_time.isoformat() if self.attempt_time else None,
            'score': self.score,
            'detailed_results': json.loads(self.detailed_results) if self.detailed_results else {}
        }

class QuestionPattern(db.Model):
    __tablename__ = 'question_patterns'
    
    pattern_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = db.Column(db.String(36), db.ForeignKey('topics.topic_id'), nullable=False)
    gate_year = db.Column(db.String(4), nullable=False)
    average_weightage = db.Column(db.Float, nullable=False)
    common_question_types = db.Column(db.Text, nullable=True)  # JSON string
    frequently_asked_concepts = db.Column(db.Text, nullable=True)  # JSON string

    def to_dict(self):
        return {
            'pattern_id': self.pattern_id,
            'topic_id': self.topic_id,
            'gate_year': self.gate_year,
            'average_weightage': self.average_weightage,
            'common_question_types': json.loads(self.common_question_types) if self.common_question_types else {},
            'frequently_asked_concepts': json.loads(self.frequently_asked_concepts) if self.frequently_asked_concepts else {}
        }


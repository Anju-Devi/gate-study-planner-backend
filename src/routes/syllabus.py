from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from src.models.database_models import db, Syllabus, Topic, Subtopic
from src.routes.auth import verify_jwt_token
import os
import json
import PyPDF2
import io
import re
from datetime import datetime

syllabus_bp = Blueprint('syllabus', __name__)

# Configuration
UPLOAD_FOLDER = '/tmp/uploads'
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(pdf_file):
    """Extract text from PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        raise Exception(f"Error extracting text from PDF: {str(e)}")

def parse_syllabus_content(text, discipline):
    """Parse syllabus text and extract topics and subtopics"""
    try:
        # This is a simplified parser - in production, you'd use more sophisticated NLP
        lines = text.split('\n')
        sections = []
        current_section = None
        current_topics = []
        
        # Common GATE section patterns
        section_patterns = [
            r'General Aptitude',
            r'Engineering Mathematics',
            r'Core Subject',
            discipline
        ]
        
        # Topic patterns (usually numbered or bulleted)
        topic_pattern = r'^(\d+\.?\s*|[A-Z]\.\s*|\*\s*|-\s*)(.+)'
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if this is a section header
            is_section = any(pattern in line for pattern in section_patterns)
            
            if is_section:
                # Save previous section
                if current_section and current_topics:
                    sections.append({
                        'section_name': current_section,
                        'topics': current_topics
                    })
                
                current_section = line
                current_topics = []
            
            # Check if this is a topic
            elif current_section:
                topic_match = re.match(topic_pattern, line)
                if topic_match:
                    topic_name = topic_match.group(2).strip()
                    current_topics.append({
                        'topic_name': topic_name,
                        'subtopics': []
                    })
                elif current_topics:
                    # This might be a subtopic or continuation
                    if len(line) > 10:  # Avoid very short lines
                        current_topics[-1]['subtopics'].append(line)
        
        # Add the last section
        if current_section and current_topics:
            sections.append({
                'section_name': current_section,
                'topics': current_topics
            })
        
        return {
            'discipline': discipline,
            'sections': sections,
            'extracted_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise Exception(f"Error parsing syllabus content: {str(e)}")

@syllabus_bp.route('/upload', methods=['POST'])
def upload_syllabus():
    """Upload and process syllabus PDF"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Get additional data
        discipline = request.form.get('discipline', 'Unknown')
        gate_year = request.form.get('gate_year', '2026')
        description = request.form.get('description', '')
        
        # Extract text from PDF
        pdf_text = extract_text_from_pdf(file)
        
        # Parse syllabus content
        parsed_content = parse_syllabus_content(pdf_text, discipline)
        
        # Create syllabus record
        syllabus = Syllabus(
            discipline=discipline,
            gate_year=gate_year,
            description=description,
            raw_content=json.dumps(parsed_content),
            uploaded_by=user_id
        )
        
        db.session.add(syllabus)
        db.session.flush()  # Get the syllabus_id
        
        # Create topic and subtopic records
        for section in parsed_content['sections']:
            for topic_data in section['topics']:
                topic = Topic(
                    syllabus_id=syllabus.syllabus_id,
                    topic_name=topic_data['topic_name'],
                    topic_description=f"Part of {section['section_name']}",
                    estimated_hours=2,  # Default estimate
                    topic_metadata=json.dumps({'section': section['section_name']})
                )
                
                db.session.add(topic)
                db.session.flush()  # Get the topic_id
                
                # Create subtopics
                for subtopic_name in topic_data['subtopics']:
                    if subtopic_name.strip():
                        subtopic = Subtopic(
                            topic_id=topic.topic_id,
                            subtopic_name=subtopic_name.strip(),
                            estimated_hours=1
                        )
                        db.session.add(subtopic)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Syllabus uploaded and processed successfully',
            'syllabus': syllabus.to_dict(),
            'topics_count': len([topic for section in parsed_content['sections'] for topic in section['topics']])
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@syllabus_bp.route('/list', methods=['GET'])
def list_syllabi():
    """Get list of available syllabi"""
    try:
        # Get query parameters
        discipline = request.args.get('discipline')
        gate_year = request.args.get('gate_year')
        
        # Build query
        query = Syllabus.query
        
        if discipline:
            query = query.filter(Syllabus.discipline.ilike(f'%{discipline}%'))
        
        if gate_year:
            query = query.filter_by(gate_year=gate_year)
        
        syllabi = query.order_by(Syllabus.uploaded_at.desc()).all()
        
        return jsonify({
            'syllabi': [syllabus.to_dict() for syllabus in syllabi]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@syllabus_bp.route('/<syllabus_id>', methods=['GET'])
def get_syllabus(syllabus_id):
    """Get detailed syllabus information with topics"""
    try:
        syllabus = Syllabus.query.get(syllabus_id)
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
        
        # Get topics with subtopics
        topics = Topic.query.filter_by(syllabus_id=syllabus_id).all()
        topics_data = []
        
        for topic in topics:
            topic_dict = topic.to_dict()
            subtopics = Subtopic.query.filter_by(topic_id=topic.topic_id).all()
            topic_dict['subtopics'] = [subtopic.to_dict() for subtopic in subtopics]
            topics_data.append(topic_dict)
        
        syllabus_data = syllabus.to_dict()
        syllabus_data['topics'] = topics_data
        
        return jsonify({'syllabus': syllabus_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@syllabus_bp.route('/disciplines', methods=['GET'])
def get_disciplines():
    """Get list of available GATE disciplines"""
    try:
        # Pre-defined GATE disciplines
        disciplines = [
            'Aerospace Engineering',
            'Agricultural Engineering',
            'Architecture and Planning',
            'Biomedical Engineering',
            'Biotechnology',
            'Chemical Engineering',
            'Chemistry',
            'Civil Engineering',
            'Computer Science and Information Technology',
            'Electrical Engineering',
            'Electronics and Communication Engineering',
            'Engineering Sciences',
            'Environmental Science and Engineering',
            'Geology and Geophysics',
            'Instrumentation Engineering',
            'Mathematics',
            'Mechanical Engineering',
            'Metallurgical Engineering',
            'Mining Engineering',
            'Naval Architecture and Marine Engineering',
            'Ocean Engineering',
            'Petroleum Engineering',
            'Physics',
            'Production and Industrial Engineering',
            'Textile Engineering and Fibre Science'
        ]
        
        return jsonify({'disciplines': disciplines}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@syllabus_bp.route('/preload', methods=['POST'])
def preload_sample_syllabi():
    """Preload sample syllabi for common GATE disciplines"""
    try:
        # Sample syllabus data for Computer Science
        cse_syllabus_content = {
            'discipline': 'Computer Science and Information Technology',
            'sections': [
                {
                    'section_name': 'General Aptitude',
                    'topics': [
                        {
                            'topic_name': 'Verbal Ability',
                            'subtopics': ['English grammar', 'Sentence completion', 'Verbal analogies', 'Word groups', 'Critical reasoning']
                        },
                        {
                            'topic_name': 'Numerical Ability',
                            'subtopics': ['Numerical computation', 'Numerical estimation', 'Numerical reasoning', 'Data interpretation']
                        }
                    ]
                },
                {
                    'section_name': 'Engineering Mathematics',
                    'topics': [
                        {
                            'topic_name': 'Discrete Mathematics',
                            'subtopics': ['Propositional and first order logic', 'Sets, relations, functions', 'Partial orders and lattices', 'Monoids, Groups', 'Graphs']
                        },
                        {
                            'topic_name': 'Linear Algebra',
                            'subtopics': ['Matrices', 'Determinants', 'System of linear equations', 'Eigenvalues and eigenvectors', 'LU decomposition']
                        }
                    ]
                },
                {
                    'section_name': 'Computer Science',
                    'topics': [
                        {
                            'topic_name': 'Programming and Data Structures',
                            'subtopics': ['Programming in C', 'Recursion', 'Arrays', 'Stacks', 'Queues', 'Linked Lists', 'Trees', 'Binary search trees', 'Binary heaps', 'Graphs']
                        },
                        {
                            'topic_name': 'Algorithms',
                            'subtopics': ['Searching', 'Sorting', 'Hashing', 'Asymptotic worst case time and space complexity', 'Algorithm design techniques', 'Graph traversals', 'Minimum spanning trees', 'Shortest paths']
                        },
                        {
                            'topic_name': 'Theory of Computation',
                            'subtopics': ['Regular expressions and finite automata', 'Context-free grammars and push-down automata', 'Regular and context-free languages', 'Pumping lemma', 'Turing machines and undecidability']
                        },
                        {
                            'topic_name': 'Computer Organization and Architecture',
                            'subtopics': ['Machine instructions and addressing modes', 'ALU', 'data‐path and control unit', 'Instruction pipelining', 'Pipeline hazards', 'Memory hierarchy', 'Cache', 'Main memory', 'Secondary storage', 'I/O interface']
                        },
                        {
                            'topic_name': 'Operating System',
                            'subtopics': ['System calls', 'Processes', 'Threads', 'Inter‐process communication', 'Concurrency and synchronization', 'Deadlock', 'CPU and I/O scheduling', 'Memory management and virtual memory', 'File systems']
                        },
                        {
                            'topic_name': 'Databases',
                            'subtopics': ['ER‐model', 'Relational model', 'Relational algebra', 'Tuple calculus', 'SQL', 'Integrity constraints', 'Normal forms', 'File organization', 'Indexing', 'B and B+ trees', 'Transactions and concurrency control']
                        },
                        {
                            'topic_name': 'Computer Networks',
                            'subtopics': ['Concept of layering', 'OSI and TCP/IP Protocol Stacks', 'Basics of packet, circuit and virtual circuit‐switching', 'Data link layer', 'Sliding window protocol', 'LAN technologies', 'Network layer', 'Routing algorithms', 'TCP/UDP and sockets', 'Application layer protocols']
                        }
                    ]
                }
            ]
        }
        
        # Create CSE syllabus
        cse_syllabus = Syllabus(
            discipline='Computer Science and Information Technology',
            gate_year='2026',
            description='Official GATE 2026 syllabus for Computer Science and Information Technology',
            raw_content=json.dumps(cse_syllabus_content)
        )
        
        db.session.add(cse_syllabus)
        db.session.flush()
        
        # Create topics and subtopics for CSE
        for section in cse_syllabus_content['sections']:
            for topic_data in section['topics']:
                topic = Topic(
                    syllabus_id=cse_syllabus.syllabus_id,
                    topic_name=topic_data['topic_name'],
                    topic_description=f"Part of {section['section_name']}",
                    estimated_hours=8 if section['section_name'] == 'Computer Science' else 4,
                    topic_metadata=json.dumps({'section': section['section_name']})
                )
                
                db.session.add(topic)
                db.session.flush()
                
                for subtopic_name in topic_data['subtopics']:
                    subtopic = Subtopic(
                        topic_id=topic.topic_id,
                        subtopic_name=subtopic_name,
                        estimated_hours=2
                    )
                    db.session.add(subtopic)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Sample syllabi preloaded successfully',
            'syllabi_created': 1
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


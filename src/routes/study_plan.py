from flask import Blueprint, request, jsonify
from src.models.database_models import db, StudyPlan, StudyPlanItem, Topic, Syllabus, User, UserProgress, QuestionPattern
from src.routes.auth import verify_jwt_token
from datetime import datetime, date, timedelta
import json
import random

study_plan_bp = Blueprint('study_plan', __name__)

def calculate_topic_priority(topic, user_progress=None, question_patterns=None):
    """Calculate priority score for a topic based on various factors"""
    base_priority = 50  # Base priority score
    
    # Factor 1: Historical GATE weightage
    if question_patterns:
        avg_weightage = sum(p.average_weightage for p in question_patterns) / len(question_patterns)
        base_priority += avg_weightage * 2  # Scale weightage impact
    
    # Factor 2: User's past performance (if available)
    if user_progress:
        avg_mastery = sum(p.mastery_score for p in user_progress if p.mastery_score) / len(user_progress)
        if avg_mastery < 60:  # Low mastery = higher priority
            base_priority += (60 - avg_mastery) * 0.5
    
    # Factor 3: Topic difficulty (estimated by hours)
    if topic.estimated_hours:
        if topic.estimated_hours > 6:  # Complex topics get higher priority
            base_priority += 10
    
    return min(100, max(0, base_priority))  # Clamp between 0-100

def generate_adaptive_schedule(topics, start_date, end_date, daily_hours=4, user_preferences=None):
    """Generate an adaptive study schedule"""
    try:
        # Calculate available study days
        total_days = (end_date - start_date).days + 1
        total_hours = total_days * daily_hours
        
        # Calculate total estimated hours needed
        total_estimated_hours = sum(topic['estimated_hours'] for topic in topics)
        
        # Adjust hours if needed
        if total_estimated_hours > total_hours:
            # Scale down hours proportionally
            scale_factor = total_hours / total_estimated_hours
            for topic in topics:
                topic['adjusted_hours'] = max(1, int(topic['estimated_hours'] * scale_factor))
        else:
            for topic in topics:
                topic['adjusted_hours'] = topic['estimated_hours']
        
        # Sort topics by priority (highest first)
        topics.sort(key=lambda x: x['priority'], reverse=True)
        
        # Generate schedule
        schedule = []
        current_date = start_date
        
        for topic in topics:
            hours_remaining = topic['adjusted_hours']
            
            while hours_remaining > 0 and current_date <= end_date:
                # Determine hours for this day
                hours_today = min(hours_remaining, daily_hours)
                
                schedule.append({
                    'topic_id': topic['topic_id'],
                    'topic_name': topic['topic_name'],
                    'scheduled_date': current_date,
                    'scheduled_hours': hours_today
                })
                
                hours_remaining -= hours_today
                current_date += timedelta(days=1)
        
        return schedule
        
    except Exception as e:
        raise Exception(f"Error generating schedule: {str(e)}")

@study_plan_bp.route('/generate', methods=['POST'])
def generate_study_plan():
    """Generate a personalized study plan"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['syllabus_id', 'start_date', 'end_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Parse dates
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
        if start_date >= end_date:
            return jsonify({'error': 'End date must be after start date'}), 400
        
        # Get syllabus and topics
        syllabus = Syllabus.query.get(data['syllabus_id'])
        if not syllabus:
            return jsonify({'error': 'Syllabus not found'}), 404
        
        topics = Topic.query.filter_by(syllabus_id=data['syllabus_id']).all()
        if not topics:
            return jsonify({'error': 'No topics found for this syllabus'}), 404
        
        # Get user preferences
        user = User.query.get(user_id)
        user_preferences = json.loads(user.preferences) if user.preferences else {}
        daily_hours = data.get('daily_hours', user_preferences.get('daily_hours', 4))
        weak_areas = data.get('weak_areas', user_preferences.get('weak_areas', []))
        
        # Prepare topics data with priorities
        topics_data = []
        for topic in topics:
            # Get user's past progress for this topic
            user_progress = UserProgress.query.filter_by(
                user_id=user_id, 
                topic_id=topic.topic_id
            ).all()
            
            # Get question patterns for this topic
            question_patterns = QuestionPattern.query.filter_by(
                topic_id=topic.topic_id
            ).all()
            
            # Calculate priority
            priority = calculate_topic_priority(topic, user_progress, question_patterns)
            
            # Boost priority for weak areas
            if topic.topic_name in weak_areas:
                priority += 20
            
            topics_data.append({
                'topic_id': topic.topic_id,
                'topic_name': topic.topic_name,
                'estimated_hours': topic.estimated_hours or 4,
                'priority': priority
            })
        
        # Generate adaptive schedule
        schedule = generate_adaptive_schedule(
            topics_data, start_date, end_date, daily_hours, user_preferences
        )
        
        # Create study plan record
        study_plan = StudyPlan(
            user_id=user_id,
            syllabus_id=data['syllabus_id'],
            start_date=start_date,
            end_date=end_date,
            plan_status='generated',
            plan_details=json.dumps({
                'daily_hours': daily_hours,
                'weak_areas': weak_areas,
                'total_topics': len(topics_data),
                'generation_algorithm': 'adaptive_priority_based'
            })
        )
        
        db.session.add(study_plan)
        db.session.flush()  # Get the plan_id
        
        # Create study plan items
        for item in schedule:
            study_plan_item = StudyPlanItem(
                plan_id=study_plan.plan_id,
                topic_id=item['topic_id'],
                scheduled_date=item['scheduled_date'],
                scheduled_hours=item['scheduled_hours'],
                status='pending'
            )
            db.session.add(study_plan_item)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Study plan generated successfully',
            'study_plan': study_plan.to_dict(),
            'schedule_items': len(schedule),
            'total_study_days': (end_date - start_date).days + 1
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@study_plan_bp.route('/list', methods=['GET'])
def list_study_plans():
    """Get user's study plans"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get user's study plans
        study_plans = StudyPlan.query.filter_by(user_id=user_id).order_by(
            StudyPlan.generated_at.desc()
        ).all()
        
        plans_data = []
        for plan in study_plans:
            plan_dict = plan.to_dict()
            
            # Get syllabus info
            syllabus = Syllabus.query.get(plan.syllabus_id)
            plan_dict['syllabus'] = syllabus.to_dict() if syllabus else None
            
            # Get progress statistics
            total_items = StudyPlanItem.query.filter_by(plan_id=plan.plan_id).count()
            completed_items = StudyPlanItem.query.filter_by(
                plan_id=plan.plan_id, status='completed'
            ).count()
            
            plan_dict['progress'] = {
                'total_items': total_items,
                'completed_items': completed_items,
                'completion_percentage': (completed_items / total_items * 100) if total_items > 0 else 0
            }
            
            plans_data.append(plan_dict)
        
        return jsonify({'study_plans': plans_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@study_plan_bp.route('/<plan_id>', methods=['GET'])
def get_study_plan(plan_id):
    """Get detailed study plan with schedule"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get study plan
        study_plan = StudyPlan.query.filter_by(
            plan_id=plan_id, user_id=user_id
        ).first()
        
        if not study_plan:
            return jsonify({'error': 'Study plan not found'}), 404
        
        # Get study plan items with topic details
        items = db.session.query(StudyPlanItem, Topic).join(
            Topic, StudyPlanItem.topic_id == Topic.topic_id
        ).filter(StudyPlanItem.plan_id == plan_id).order_by(
            StudyPlanItem.scheduled_date
        ).all()
        
        schedule = []
        for item, topic in items:
            item_dict = item.to_dict()
            item_dict['topic'] = topic.to_dict()
            schedule.append(item_dict)
        
        # Get syllabus info
        syllabus = Syllabus.query.get(study_plan.syllabus_id)
        
        plan_data = study_plan.to_dict()
        plan_data['syllabus'] = syllabus.to_dict() if syllabus else None
        plan_data['schedule'] = schedule
        
        return jsonify({'study_plan': plan_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@study_plan_bp.route('/<plan_id>/activate', methods=['POST'])
def activate_study_plan(plan_id):
    """Activate a study plan"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get study plan
        study_plan = StudyPlan.query.filter_by(
            plan_id=plan_id, user_id=user_id
        ).first()
        
        if not study_plan:
            return jsonify({'error': 'Study plan not found'}), 404
        
        # Deactivate other active plans
        StudyPlan.query.filter_by(
            user_id=user_id, plan_status='active'
        ).update({'plan_status': 'archived'})
        
        # Activate this plan
        study_plan.plan_status = 'active'
        db.session.commit()
        
        return jsonify({
            'message': 'Study plan activated successfully',
            'study_plan': study_plan.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@study_plan_bp.route('/today', methods=['GET'])
def get_today_schedule():
    """Get today's study schedule for the active plan"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get active study plan
        active_plan = StudyPlan.query.filter_by(
            user_id=user_id, plan_status='active'
        ).first()
        
        if not active_plan:
            return jsonify({'error': 'No active study plan found'}), 404
        
        # Get today's schedule
        today = date.today()
        items = db.session.query(StudyPlanItem, Topic).join(
            Topic, StudyPlanItem.topic_id == Topic.topic_id
        ).filter(
            StudyPlanItem.plan_id == active_plan.plan_id,
            StudyPlanItem.scheduled_date == today
        ).all()
        
        schedule = []
        for item, topic in items:
            item_dict = item.to_dict()
            item_dict['topic'] = topic.to_dict()
            schedule.append(item_dict)
        
        return jsonify({
            'date': today.isoformat(),
            'schedule': schedule,
            'study_plan': active_plan.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@study_plan_bp.route('/item/<item_id>/update', methods=['PUT'])
def update_study_item(item_id):
    """Update study plan item status"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get study plan item
        item = db.session.query(StudyPlanItem).join(
            StudyPlan, StudyPlanItem.plan_id == StudyPlan.plan_id
        ).filter(
            StudyPlanItem.item_id == item_id,
            StudyPlan.user_id == user_id
        ).first()
        
        if not item:
            return jsonify({'error': 'Study plan item not found'}), 404
        
        data = request.get_json()
        
        # Update allowed fields
        if 'status' in data:
            if data['status'] in ['pending', 'in_progress', 'completed', 'skipped']:
                item.status = data['status']
        
        if 'notes' in data:
            item.notes = data['notes']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Study plan item updated successfully',
            'item': item.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


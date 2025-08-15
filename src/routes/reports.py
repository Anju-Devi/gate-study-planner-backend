from flask import Blueprint, request, jsonify, send_file
from src.models.database_models import db, StudyPlan, StudyPlanItem, Topic, UserProgress, User
from src.routes.auth import verify_jwt_token
from datetime import datetime, date, timedelta
import json
import io
import csv
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

reports_bp = Blueprint('reports', __name__)

def generate_study_plan_data(plan_id, user_id, filters=None):
    """Generate comprehensive study plan data for reports"""
    try:
        # Get study plan
        study_plan = StudyPlan.query.filter_by(
            plan_id=plan_id, user_id=user_id
        ).first()
        
        if not study_plan:
            return None
        
        # Get study plan items with topic details
        query = db.session.query(StudyPlanItem, Topic).join(
            Topic, StudyPlanItem.topic_id == Topic.topic_id
        ).filter(StudyPlanItem.plan_id == plan_id)
        
        # Apply filters if provided
        if filters:
            if filters.get('start_date'):
                start_date = datetime.strptime(filters['start_date'], '%Y-%m-%d').date()
                query = query.filter(StudyPlanItem.scheduled_date >= start_date)
            
            if filters.get('end_date'):
                end_date = datetime.strptime(filters['end_date'], '%Y-%m-%d').date()
                query = query.filter(StudyPlanItem.scheduled_date <= end_date)
            
            if filters.get('status'):
                query = query.filter(StudyPlanItem.status == filters['status'])
            
            if filters.get('topic_ids'):
                query = query.filter(StudyPlanItem.topic_id.in_(filters['topic_ids']))
        
        items = query.order_by(StudyPlanItem.scheduled_date).all()
        
        # Process data
        schedule_data = []
        topic_summary = {}
        status_summary = {'pending': 0, 'in_progress': 0, 'completed': 0, 'skipped': 0}
        total_hours = 0
        
        for item, topic in items:
            item_dict = item.to_dict()
            item_dict['topic'] = topic.to_dict()
            schedule_data.append(item_dict)
            
            # Update summaries
            status_summary[item.status] += 1
            total_hours += item.scheduled_hours
            
            if topic.topic_name not in topic_summary:
                topic_summary[topic.topic_name] = {
                    'total_hours': 0,
                    'completed_hours': 0,
                    'items': 0,
                    'completed_items': 0
                }
            
            topic_summary[topic.topic_name]['total_hours'] += item.scheduled_hours
            topic_summary[topic.topic_name]['items'] += 1
            
            if item.status == 'completed':
                topic_summary[topic.topic_name]['completed_hours'] += item.scheduled_hours
                topic_summary[topic.topic_name]['completed_items'] += 1
        
        # Calculate progress metrics
        total_items = len(schedule_data)
        completed_items = status_summary['completed']
        completion_percentage = (completed_items / total_items * 100) if total_items > 0 else 0
        
        # Get user progress data
        user_progress = UserProgress.query.filter_by(user_id=user_id).all()
        progress_by_topic = {}
        for progress in user_progress:
            if progress.topic_id not in progress_by_topic:
                progress_by_topic[progress.topic_id] = []
            progress_by_topic[progress.topic_id].append(progress.to_dict())
        
        return {
            'study_plan': study_plan.to_dict(),
            'schedule': schedule_data,
            'summary': {
                'total_items': total_items,
                'total_hours': total_hours,
                'completion_percentage': completion_percentage,
                'status_breakdown': status_summary,
                'topic_summary': topic_summary
            },
            'user_progress': progress_by_topic,
            'generated_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise Exception(f"Error generating report data: {str(e)}")

@reports_bp.route('/study-plan/<plan_id>', methods=['GET'])
def get_study_plan_report(plan_id):
    """Get study plan report data"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get query parameters for filtering
        filters = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'status': request.args.get('status'),
            'topic_ids': request.args.getlist('topic_ids')
        }
        
        # Remove None values
        filters = {k: v for k, v in filters.items() if v}
        
        # Generate report data
        report_data = generate_study_plan_data(plan_id, user_id, filters)
        
        if not report_data:
            return jsonify({'error': 'Study plan not found'}), 404
        
        return jsonify({'report': report_data}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@reports_bp.route('/study-plan/<plan_id>/export/pdf', methods=['GET'])
def export_study_plan_pdf(plan_id):
    """Export study plan as PDF"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get filters
        filters = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'status': request.args.get('status')
        }
        filters = {k: v for k, v in filters.items() if v}
        
        # Generate report data
        report_data = generate_study_plan_data(plan_id, user_id, filters)
        
        if not report_data:
            return jsonify({'error': 'Study plan not found'}), 404
        
        # Create PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        
        title = Paragraph("GATE Study Plan Report", title_style)
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Study plan info
        plan_info = [
            ['Study Plan ID:', report_data['study_plan']['plan_id']],
            ['Discipline:', report_data['study_plan'].get('syllabus', {}).get('discipline', 'N/A')],
            ['Start Date:', report_data['study_plan']['start_date']],
            ['End Date:', report_data['study_plan']['end_date']],
            ['Status:', report_data['study_plan']['plan_status']],
            ['Generated:', report_data['generated_at'][:10]]
        ]
        
        info_table = Table(plan_info, colWidths=[2*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # Summary section
        summary_title = Paragraph("Summary", styles['Heading2'])
        story.append(summary_title)
        
        summary = report_data['summary']
        summary_data = [
            ['Total Items:', str(summary['total_items'])],
            ['Total Hours:', str(summary['total_hours'])],
            ['Completion:', f"{summary['completion_percentage']:.1f}%"],
            ['Completed:', str(summary['status_breakdown']['completed'])],
            ['Pending:', str(summary['status_breakdown']['pending'])],
            ['In Progress:', str(summary['status_breakdown']['in_progress'])],
            ['Skipped:', str(summary['status_breakdown']['skipped'])]
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 1.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        # Schedule section
        schedule_title = Paragraph("Study Schedule", styles['Heading2'])
        story.append(schedule_title)
        
        # Create schedule table
        schedule_data = [['Date', 'Topic', 'Hours', 'Status']]
        for item in report_data['schedule'][:50]:  # Limit to first 50 items for PDF
            schedule_data.append([
                item['scheduled_date'],
                item['topic']['topic_name'][:30] + '...' if len(item['topic']['topic_name']) > 30 else item['topic']['topic_name'],
                str(item['scheduled_hours']),
                item['status'].title()
            ])
        
        schedule_table = Table(schedule_data, colWidths=[1.2*inch, 3*inch, 0.8*inch, 1*inch])
        schedule_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8)
        ]))
        
        story.append(schedule_table)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'study_plan_{plan_id}_{datetime.now().strftime("%Y%m%d")}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@reports_bp.route('/study-plan/<plan_id>/export/csv', methods=['GET'])
def export_study_plan_csv(plan_id):
    """Export study plan as CSV"""
    try:
        # Verify authentication
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        user_id = verify_jwt_token(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Get filters
        filters = {
            'start_date': request.args.get('start_date'),
            'end_date': request.args.get('end_date'),
            'status': request.args.get('status')
        }
        filters = {k: v for k, v in filters.items() if v}
        
        # Generate report data
        report_data = generate_study_plan_data(plan_id, user_id, filters)
        
        if not report_data:
            return jsonify({'error': 'Study plan not found'}), 404
        
        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Date', 'Topic', 'Hours', 'Status', 'Notes'])
        
        # Write data
        for item in report_data['schedule']:
            writer.writerow([
                item['scheduled_date'],
                item['topic']['topic_name'],
                item['scheduled_hours'],
                item['status'],
                item.get('notes', '')
            ])
        
        # Convert to bytes
        output.seek(0)
        buffer = io.BytesIO()
        buffer.write(output.getvalue().encode('utf-8'))
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'study_plan_{plan_id}_{datetime.now().strftime("%Y%m%d")}.csv',
            mimetype='text/csv'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@reports_bp.route('/progress/<user_id>', methods=['GET'])
def get_progress_report(user_id):
    """Get comprehensive progress report for a user"""
    try:
        # Verify authentication (users can only access their own reports)
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization token required'}), 401
        
        token = auth_header.split(' ')[1]
        authenticated_user_id = verify_jwt_token(token)
        
        if not authenticated_user_id or authenticated_user_id != user_id:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Get date range
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get user progress
        query = UserProgress.query.filter_by(user_id=user_id)
        
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(UserProgress.progress_date >= start_date)
        
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(UserProgress.progress_date <= end_date)
        
        progress_records = query.order_by(UserProgress.progress_date.desc()).all()
        
        # Process progress data
        total_hours = sum(p.hours_studied for p in progress_records)
        avg_mastery = sum(p.mastery_score for p in progress_records if p.mastery_score) / len(progress_records) if progress_records else 0
        
        # Group by topic
        topic_progress = {}
        for progress in progress_records:
            topic_id = progress.topic_id
            if topic_id not in topic_progress:
                topic_progress[topic_id] = {
                    'total_hours': 0,
                    'sessions': 0,
                    'latest_mastery': 0,
                    'progress_trend': []
                }
            
            topic_progress[topic_id]['total_hours'] += progress.hours_studied
            topic_progress[topic_id]['sessions'] += 1
            if progress.mastery_score:
                topic_progress[topic_id]['latest_mastery'] = progress.mastery_score
            
            topic_progress[topic_id]['progress_trend'].append({
                'date': progress.progress_date.isoformat(),
                'hours': progress.hours_studied,
                'mastery': progress.mastery_score
            })
        
        # Get topic names
        topic_ids = list(topic_progress.keys())
        topics = Topic.query.filter(Topic.topic_id.in_(topic_ids)).all()
        topic_names = {t.topic_id: t.topic_name for t in topics}
        
        # Add topic names to progress data
        for topic_id, data in topic_progress.items():
            data['topic_name'] = topic_names.get(topic_id, 'Unknown Topic')
        
        return jsonify({
            'progress_report': {
                'user_id': user_id,
                'total_hours_studied': total_hours,
                'average_mastery_score': avg_mastery,
                'total_sessions': len(progress_records),
                'topic_breakdown': topic_progress,
                'generated_at': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


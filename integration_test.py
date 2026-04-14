import unittest
import time
from app import app, db, User, Skill, UserSkill, SavedJobs, load_skills, user_content_profile, calculate_match
from werkzeug.security import generate_password_hash

class IntegrationTests(unittest.TestCase):
    
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            user = User(
                name="test test",email="user@gmail.com",password=generate_password_hash("Password@123"),career_goal="data analyst",experience_level="Junior")
            db.session.add(user)
            db.session.commit()
    
    
    def login(self):
        return self.client.post('/login', data={'email': 'user@gmail.com','password': 'Password@123'
        }, follow_redirects=True)
    
    def test_signup(self):
        response = self.client.post('/signup', data={
            'firstname': 'user','lastname': 'user',
            'email': 'user2@gmail.com',
            'password': 'Password@123','confirm-password': 'Password@123'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        
        response = self.client.post('/login', data={
            'email': 'user2@gmail.com',
            'password': 'Password@123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_incorrect_password(self):
        response= self.client.post('/login', data={
           'email': 'user@gmail.com',
            'password':'password123'
        }, follow_redirects=True)
        self.assertIn(b'Invalid email or password', response.data)
    
    def test_correct_password(self):
        response= self.client.post('/login', data={
           'email': 'user@gmail.com',
            'password':'Password@123'
        }, follow_redirects=True)
        self.assertIn(b'Login successful!', response.data)
    
    def test_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_job_details_page(self):
        response=self.client.get('/job/9999999999999',follow_redirects=True)
        self.assertIn(b'This job may have expired, please browse different jobs', response.data)

    def test_add_skill(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        self.client.post('/upload_cv', data={
            'action': 'add_skill',
            'skills': 'python'
        })
        with app.app_context():
            user = User.query.filter_by(email='user@gmail.com').first()
            user_skills = [us.skill.name for us in user.skills]
            self.assertIn('python', user_skills)
    
    def test_update_email(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        response = self.client.post('/edit_account', data={
            'action': 'update_email',
            'email': 'user123@gmail.com'
        }, follow_redirects=True)
        self.assertIn(b'Email updated', response.data)
    
    def test_update_no_email(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        response = self.client.post('/edit_account', data={
            'action': 'update_email',
            'email': ''
        }, follow_redirects=True)
        self.assertIn(b'Email cannot be empty', response.data)
    
    def test_add_invalid_skill(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })

        response = self.client.post('/upload_cv', data={
        'action': 'add_skill',
        'skills': 'hello'},follow_redirects=True)
        self.assertIn(b'is not a valid skill', response.data)
    
    def test_add_no_skill(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })

        response = self.client.post('/upload_cv', data={
        'action': 'add_skill',
        'skills': ''},follow_redirects=True)
        self.assertIn(b'Enter a skill', response.data)

    def test_add_existing_skill(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        self.client.post('/upload_cv', data={
        'action': 'add_skill',
        'skills': 'python'
        })


        response = self.client.post('/upload_cv', data={
        'action': 'add_skill',
        'skills': 'python'},follow_redirects=True)
        self.assertIn(b'You already added that skill', response.data)

    def test_logout(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        response=self.client.get('/logout', follow_redirects=True)
        self.assertIn(b'Logged out', response.data)

    def test_duplicate_email(self):
        response = self.client.post('/signup', data={
            'firstname': 'user','lastname': 'user',
            'email': 'user@gmail.com',
            'password': 'Password@123','confirm-password': 'Password@123'}, follow_redirects=True)
        self.assertIn(b'Email already exists, signin to your account', response.data)
    
    def test_password_mismatch(self):
        response = self.client.post('/signup', data={
            'firstname': 'user','lastname': 'user',
            'email': 'user2@gmail.com',
            'password': 'Password@123','confirm-password': 'Password123'}, follow_redirects=True)
        self.assertIn(b'Passwords do not match', response.data)

    def test_job_scoring(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
      
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        combined_skills=['python','sql','java','oop']   
        job_skills = ['python', 'sql', 'excel']
        profile_text='python sql java data analyst junior'
        job_desc='data analyst with experience in python , sql and excel'
        job_title = 'junior Data Analyst'
        score = calculate_match(combined_skills, profile_text, job_skills, job_desc, job_title)
        self.assertGreater(score, 50)

    def test_job_low_match(self):
        self.client.post('/login', data={
            'email': 'user2@gmail.com',
            'password': 'Password@123'
        })
        self.client.post('/upload_cv', data={
            'action': 'add_career_goal',
            'career_goal': 'Teacher'
        })
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        combined_skills=['teaching ','communication','collaboration']   
        job_skills = ['python', 'sql', 'excel']
        profile_text='teaching communication collaboration teacher'
        job_desc='data analyst with experience in python , sql and excel'
        job_title = 'junior Data Analyst'
        score = calculate_match(combined_skills, profile_text, job_skills, job_desc, job_title)
        self.assertLess(score, 20)
    
    def test_access(self):
        response = self.client.get('/account_page', follow_redirects=True)
        self.assertIn(b'Please Login first', response.data)
    
    def test_scoring_time(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        start=time.time()

        response = self.client.get('/')
        end=time.time()
        self.assertEqual(response.status_code, 200)
        self.assertLess(end - start, 10)

    def test_delete_skill(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })
        self.client.post('/upload_cv', data={
        'action': 'add_skill',
        'skills': 'python'
        })
        with app.app_context():
            user = User.query.filter_by(email='user@gmail.com').first()
            skill_id = user.skills[0].skill_id
            
            response = self.client.post('/upload_cv', data={
            'action': 'delete_skill',
            'skill_id': skill_id
            }, follow_redirects=True)
            self.assertIn(b'Skill removed', response.data)
        
    def test_contact_us(self):
        self.client.post('/login', data={
            'email': 'user@gmail.com',
            'password': 'Password@123'
        })

        response = self.client.post('/contact_us', data={
        'name': 'test test',
        'email': 'user@gmail.com',
        'subject': 'Need help',
        'message': 'Login issue'
        }, follow_redirects=True)
        self.assertIn(b'Contact Us', response.data)
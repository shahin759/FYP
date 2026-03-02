from flask import Flask, render_template, abort, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import pandas as pd
import time


app = Flask(__name__)

app.secret_key = "12345678"



app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///seeker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

API_KEY = "7eabd148-3685-4360-be0c-555c97ec868c"
BASE_URL = "https://www.reed.co.uk/api/1.0"

class User(db.Model):
    __tablename__="user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100))
    skills = db.relationships("UserSkill",back_populates="user",cascade="all, delete-orphan")

class Skill(db.Model):
    __tablename__="skill"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    users = db.relationships("UserSkill",back_populates="skill",cascade="all, delete-orphan")

class UserSkill(db.Model):
    __tablename__="user_skill"
    id = db.Column(db.Integer, primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skill.id"), nullable=False)
    user = db.relationship("User", back_populates="skills")
    skill = db.relationship("Skill", back_populates="users")

    __table_args__ = (
        db.UniqueConstraint("user_id", "skill_id", name="uq_user_skill"),
    )

    def __repr__(self):
        return f'<User {self.email}>'

with app.app_context():
    db.create_all()
 

@app.route("/")
def home_page():
    search_keywords = request.args.get('keywords', '')
    location = request.args.get('location', '')
    url = f"{BASE_URL}/search"

    params = {}
    if search_keywords:
        params['keywords'] = search_keywords
    if location:
        params['locationName'] = location

    try:
        response = requests.get(url,params=params, auth=(API_KEY, ""),  timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"Error fetching jobs: {e}", 500
        
    jobs = data.get("results", [])[:30]

    return render_template("home_page.html",jobs = jobs , search_keywords=search_keywords,
    location=location,total_results=len(jobs))

@app.route("/job/<int:job_id>")
def job_details(job_id):
    url = f"{BASE_URL}/jobs/{job_id}"
    
    try:
        response = requests.get(url, auth=(API_KEY, ""), timeout=10)
        
        if response.status_code == 404:
            abort(404)
        
        response.raise_for_status()  
        job = response.json()  
        
        return render_template("job_details.html", job=job)
    
    except requests.RequestException as e:
        print(f"Error details: {e}")
        return f"Error fetching job details: {e}", 500


    
@app.route("/login", methods=["GET", "POST"])
def login_page():
 if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember')
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user'] = email
            if remember:
                session.permanent = True
            flash('Login successful!', 'success')
            return redirect(url_for('home_page'))
        else:
            flash('Invalid email or password', 'error')
            return redirect(url_for('login_page'))
    
 return render_template('login_page.html')

@app.route("/signup", methods=["GET", "POST"])
def signup_page():
  if request.method =='POST':
    firstname= request.form.get('firstname')
    lastname= request.form.get('lastname')
    email=request.form.get('email')
    password=request.form.get('password')
    confirm_password=request.form.get('confirm_password')

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('Email already exists, signin to your account','error')
        return redirect(url_for('signup_page'))

    if password != confirm_password:
        flash('Passwords do not match!','error')
        return redirect(url_for('signup'))
        
    hashed_password = generate_password_hash(password)
    new_user = User(name= str(firstname) + " " + str(lastname) , email=email, password=hashed_password)
        
    db.session.add(new_user)
    db.session.commit()
        
  
    flash('Account created successfully! Please login.', 'success')
    return redirect(url_for('login_page'))
    
  return render_template('signup_page.html')
    
@app.route('/account-page', methods=['GET'])
def account_page():
    if 'user' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login_page'))
    
    user = User.query.filter_by(email=session['user']).first()
    
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))
    
    return render_template('account_page.html', user=user)

@app.route('/courses')
def courses_page():
    search_course = request.args.get('courses', '').strip().lower()

    params = {}
    if search_course:
     params['courses'] = search_course
    try:
        df=pd.read_csv('csv/courses.csv')
        course_list=df.to_dict('records')
    except FileNotFoundError:
        flash("Courses file not found")
        return render_template('courses_page.html',courses=[])
        
    if search_course:
        course_list = [
            c for c in course_list
            if search_course in str(c.get('course_title', '')).lower()
            or search_course in str(c.get('provider', '')).lower()
            or search_course in str(c.get('skills', '')).lower()
        ]

    return render_template("courses_page.html",courses=course_list,search_course=request.args.get('course', ''), total_results=len(course_list))


@app.route('/upload_cv', methods=["GET", "POST"])
def upload_cv():
    if 'user' not in session:
        flash('Login first', 'error')
        return redirect(url_for('login_page'))

    user = User.query.filter_by(email=session['user']).first()

    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))

    if request.method =='POST':
     skillInput= request.form.get('skillInput')

    user.skills=skillInput
    db.session.commit()
  
    flash('Skill addede successfully', 'success')
  
    return render_template("upload_cv.html", user=user)

@app.route('/logout')
def logout():
    session.pop('user',None)
    flash('Logged out','success')
    return redirect (url_for('home_page'))

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

if __name__ == "__main__":
    app.run(debug=True)
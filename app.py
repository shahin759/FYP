from flask import Flask, render_template, abort, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import pandas as pd
import time
from werkzeug.security import generate_password_hash
import csv
import re
from pdfminer.high_level import extract_text



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
    experience_level=db.Column(db.String(100))
    carrer_goal= db.Column(db.String(100))
    skills = db.relationship("UserSkill",back_populates="user",cascade="all, delete-orphan")

class Skill(db.Model):
    __tablename__="skill"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    users = db.relationship("UserSkill",back_populates="skill",cascade="all, delete-orphan")

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
        response = requests.get(url, params=params, auth=(API_KEY, ""), timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"Error fetching jobs: {e}", 500

    jobs = data.get("results", [])[:30]


    user_skills = []
    user_profile_text = ""

    if "user" in session:
        user = User.query.filter_by(email=session["user"]).first()
        if user:
            user_skills = [us.skill.name for us in user.skills]

            user_profile_text = " ".join(user_skills)

            if user.carrer_goal:
                user_profile_text += " " + user.carrer_goal

            if user.experience_level:
                user_profile_text += " " + user.experience_level

    skills_list = load_skills_from_csv("csv/skills.csv")


    for job in jobs:
        desc = job.get("jobDescription", "") or ""

        job_desc_norm = " ".join(str(desc).lower().split())
        job_skills = extract_skills_from_text(job_desc_norm, skills_list)

        skill_score = skill_overlap_score(user_skills, job_skills)

        cosine_score = tfidf_cosine_score(user_profile_text, desc)

        job["match_score"] = final_match_score(skill_score, cosine_score)
        job['experience_level'] = extract_experience_level(job.get('jobTitle', ''))


    jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    

    return render_template(
        "home_page.html",
        jobs=jobs,
        search_keywords=search_keywords,
        location=location,
        total_results=len(jobs)
    )

@app.route("/job/<int:job_id>")
def job_details(job_id):
    url = f"{BASE_URL}/jobs/{job_id}"

    try:
        response = requests.get(url, auth=(API_KEY, ""), timeout=10)
        if response.status_code == 404:
            abort(404)
        response.raise_for_status()
        job = response.json()

        skills_list = load_skills_from_csv("csv/skills.csv")
        job_desc = job.get("jobDescription") or ""
        job_desc_norm = " ".join(str(job_desc).lower().split())
        job_skills = extract_skills_from_text(job_desc_norm, skills_list)

        user_skills = []
        match_result = None
        recommended_courses = []

        if "user" in session:
            user = User.query.filter_by(email=session["user"]).first()
            if user:
                user_skills = [us.skill.name for us in user.skills]

                # Calculate full match analysis
                user_set = {s.lower().strip() for s in user_skills}
                job_set  = {s.lower().strip() for s in job_skills}

                matching = sorted(user_set & job_set)
                missing  = sorted(job_set - user_set)

                skill_score  = skill_overlap_score(user_skills, job_skills)
                cosine_score = tfidf_cosine_score(
                    build_user_profile_text(user), job_desc
                )
                score = final_match_score(skill_score, cosine_score)

                match_result = {
                    'score':          score,
                    'matching_skills': matching,
                    'missing_skills':  missing,
                    'total_matching':  len(matching),
                    'job_total_skills': len(job_set)
                }

                # Course recommendations for missing skills
                if missing:
                    recommended_courses = get_courses_for_skills(missing)

        return render_template("job_details.html",
                               job=job,
                               job_skills=job_skills,
                               user_skills=user_skills,
                               match_result=match_result,
                               recommended_courses=recommended_courses)

    except requests.RequestException as e:
        print(f"Error details: {e}")
        return f"Error fetching job details: {e}", 500

def get_courses_for_skills(missing_skills: list[str]) -> list[dict]:
    courses = []
    try:
        df = pd.read_csv('csv/courses.csv')
        for skill in missing_skills[:10]:
            matches = df[df['skills'].str.contains(
                skill, case=False, na=False
            )]
            for _, course in matches.iterrows():
                course_dict = course.to_dict()
                if course_dict not in courses:
                    courses.append(course_dict)
                if len(courses) >= 5:
                    return courses
    except Exception as e:
        print(f"Course error: {e}")
    return courses

    
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

    if request.method == 'POST':
        action = request.form.get("action")

        if action == "add_skill":
            skill_input = request.form.get('skills', '').strip()

            if not skill_input:
                flash("Enter a skill", "error")
                return redirect(url_for('upload_cv'))

            skill = Skill.query.filter_by(name=skill_input).first()
            if not skill:
                skill = Skill(name=skill_input)
                db.session.add(skill)
                db.session.flush()

            exists = UserSkill.query.filter_by(
                user_id=user.id,
                skill_id=skill.id
            ).first()

            if exists:
                flash('You already added that skill', 'info')
            else:
                db.session.add(UserSkill(user_id=user.id, skill_id=skill.id))
                db.session.commit()
                flash('Skill added successfully', 'success')

      
        elif action == "delete_skill":
            skill_id = request.form.get("skill_id")
            link = UserSkill.query.filter_by(
                user_id=user.id,
                skill_id=skill_id
            ).first()

            if link:
                db.session.delete(link)
                db.session.commit()
                flash("Skill removed", "success")

        elif action=="add_goals":
          goals_input=request.form.get("goals")
          user.carrer_goal=goals_input
          db.session.commit()
          flash("carrer goal added", "success")

        elif action == "delete_goal":
          user.carrer_goal = None
          db.session.commit()
          flash("Career goal removed", "success")

        elif action=="save_experience":
            experience=request.form.get("experience")
            user.experience_level=experience
            db.session.commit()
            flash("saved","success")

    return render_template("upload_cv.html", user=user)



def load_skills_from_csv(path: str) -> list[str]:
    skills = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            s = row[0].strip()
            if s and s.lower() != "skill":  
                skills.append(s)
    return skills

def pdf_to_text(pdf_path: str) -> str:
    text = extract_text(pdf_path) or ""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_skills_from_text(text: str, skills: list[str]) -> list[str]:
    found = set()

    for skill in sorted(skills, key=len, reverse=True):
        s = skill.strip()
        if not s:
            continue

        s_low = s.lower()

        pattern = r"\b" + re.escape(s_low) + r"\b"
        if re.search(pattern, text):
            found.add(s) 

    return sorted(found)

import os
from werkzeug.utils import secure_filename
from flask import request, redirect, url_for, flash, session

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def allowed_pdf(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() == "pdf"

@app.route("/extract_skills_from_cv", methods=["POST"])
def extract_skills_from_cv():
    if "user" not in session:
        flash("Login first", "error")
        return redirect(url_for("login_page"))

    user = User.query.filter_by(email=session["user"]).first()
    if not user:
        flash("User not found", "error")
        return redirect(url_for("login_page"))

    file = request.files.get("cv")
    if not file or file.filename == "":
        flash("Please choose a PDF", "error")
        return redirect(url_for("upload_cv"))

    if not allowed_pdf(file.filename):
        flash("Only PDF files are allowed", "error")
        return redirect(url_for("upload_cv"))

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    filename = secure_filename(file.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(path)

    cv_text = pdf_to_text(path)
    if not cv_text:
        flash("Could not read text from PDF", "error")
        return redirect(url_for("upload_cv"))

    skills_list = load_skills_from_csv("csv/skills.csv") 
    extracted = extract_skills_from_text(cv_text, skills_list)

    added = 0
    for name in extracted:
        skill = Skill.query.filter_by(name=name).first()
        if not skill:
            skill = Skill(name=name)
            db.session.add(skill)
            db.session.flush()

        exists = UserSkill.query.filter_by(user_id=user.id, skill_id=skill.id).first()
        if not exists:
            db.session.add(UserSkill(user_id=user.id, skill_id=skill.id))
            added += 1

    db.session.commit()
    flash(f"Found {len(extracted)} skills, added {added} new", "success")
    return redirect(url_for("upload_cv"))

@app.route('/edit_account', methods=["GET", "POST"])
def edit_account():
    if 'user' not in session:
        flash('Login first', 'error')
        return redirect(url_for('login_page'))

    user = User.query.filter_by(email=session['user']).first()
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        action = request.form.get("action")

        if action == "update_email":
            new_email = request.form.get('email', '').strip()

            if not new_email:
                flash("Email cannot be empty", "error")
                return redirect(url_for("edit_account"))

            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                flash("That email is already in use", "error")
                return redirect(url_for("edit_account"))

            user.email = new_email
            db.session.commit()
            session['user'] = new_email

            flash("Email updated", "success")
            return redirect(url_for("edit_account"))

        elif action == "update_password":
            new_password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if new_password != confirm_password:
                flash("Passwords do not match", "error")
                return redirect(url_for("edit_account"))

            user.password = generate_password_hash(new_password)
            db.session.commit()

            flash("Password updated successfully", "success")
            return redirect(url_for("edit_account"))

        else:
            flash("Invalid action", "error")
            return redirect(url_for("edit_account"))

    return render_template("edit_account.html", user=user)

import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def skill_overlap_score(user_skills: list[str], job_skills: list[str]) -> float:
    u = {str(x).strip().lower() for x in user_skills if str(x).strip()}
    j = {str(x).strip().lower() for x in job_skills if str(x).strip()}
    if not j:
        return 0.0
    return (len(u & j) / len(j)) * 100.0

def tfidf_cosine_score(user_profile_text: str, job_text: str) -> float:
    user_profile_text = normalize_text(user_profile_text)
    job_text = normalize_text(job_text)
    if not user_profile_text or not job_text:
        return 0.0

    vect = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    X = vect.fit_transform([user_profile_text, job_text])
    sim = cosine_similarity(X[0:1], X[1:2])[0][0]  # 0..1
    return float(sim) * 100.0

def final_match_score(skill_score: float, cosine_score: float, w_skill=0.7, w_cos=0.3) -> int:
    return round(min(100.0, (w_skill * skill_score) + (w_cos * cosine_score)))

def build_user_profile_text(user) -> str:
    skills = [us.skill.name for us in user.skills] if user else []
    parts = [
        " ".join(skills),
        user.carrer_goal or "",
        user.experience_level or ""
    ]
    return " ".join([p for p in parts if p]).strip()

def extract_experience_level(job_title: str) ->str:
    title=(job_title or '').lower()

    if any(words in title for words in ['junior','trainee','entry','grad','graduate','intern']):
     return 'Junior'
    elif any(words in title for words in ['senior','manager','lead','specialist','director']):
     return 'Senior'
    elif any(words in title for words in ['mid','intermediate','mid-level','grad']):
     return 'Mid-level'
    else:
     return 'Not specified'
    
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
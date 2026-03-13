from flask import Flask, render_template, abort, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pdfminer.high_level import extract_text
from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams
from flask_caching import Cache
from flask_mail import Mail, Message
import requests
import pandas as pd
import time
import csv
import re
import os
import io
import secrets

app = Flask(__name__)

app.secret_key = "12345678"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///seeker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'support.seeker@gmail.com'
app.config['MAIL_PASSWORD'] = 'rdgt kwkr poup zdxg'
app.config['MAIL_DEFAULT_SENDER'] = 'support.seeker@gmail.com'

mail = Mail(app)
reset_tokens = {}
db = SQLAlchemy(app)

API_KEY = "7eabd148-3685-4360-be0c-555c97ec868c"
BASE_URL = "https://www.reed.co.uk/api/1.0"

app.config["CACHE_TYPE"] = "SimpleCache"
app.config["CACHE_DEFAULT_TIMEOUT"]=200

cache=Cache(app)
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
    page = int(request.args.get('page', 1))
    show_all = request.args.get('all') == '1'
    per_page = 20

    params = {}
    if search_keywords:
        params['keywords'] = search_keywords
    if location:
        params['locationName'] = location

    user_skills = []
    user_profile_text = ""
    user_experience = ""
    user_goal = ""

    if "user" in session:
        user = User.query.filter_by(email=session["user"]).first()
        if user:
            user_skills = [us.skill.name for us in user.skills]
            user_experience = (user.experience_level or "").lower()
            user_goal = (user.carrer_goal or "").lower()
            user_profile_text = build_user_profile_text(user)

    if "user" in session and user_goal and not search_keywords:
        params['keywords'] = user_goal

 
    try:
        filtered = get_scored_jobs(
            tuple(sorted(params.items())),
            tuple(user_skills),
            user_profile_text,
            user_experience,
            show_all
        )
    except Exception as e:
        return f"Error fetching jobs: {e}", 500

    title = "Recommended jobs for you" if "user" in session else "Login or register to view jobs suited to you"

    end = page * per_page
    jobs = filtered[:end]
    has_more = len(filtered) > end

    return render_template(
        "home_page.html",
        jobs=jobs,
        search_keywords=search_keywords,
        location=location,
        show_all=show_all,
        total_results=len(filtered),
        page=page,
        has_more=has_more,
        title=title
    )

@app.route("/job/<int:job_id>")
def job_details(job_id):
    url = f"{BASE_URL}/jobs/{job_id}"

    try:
        job=fetch_job(job_id)

        skills_list = load_skills("csv/skills.csv")
        job_desc = job.get("jobDescription") or ""
        job_desc_norm = " ".join(str(job_desc).lower().split())
        job_skills = extract_skills_from_description(job_desc_norm, skills_list)

        user_skills = []
        match_result = None
        recommended_courses = []

        if "user" in session:
            user = User.query.filter_by(email=session["user"]).first()
            if user:
                user_skills = [us.skill.name for us in user.skills]

                user_set = {s.lower().strip() for s in user_skills}
                job_set = {s.lower().strip() for s in job_skills}

                matching = sorted(user_set & job_set)
                missing = sorted(job_set - user_set)

                skill_score = skill_overlap_score(user_skills, job_skills)
                cosine_score = tfidf_cosine_score(
                    build_user_profile_text(user), job_desc
                )
                score = final_match_score(skill_score, cosine_score)

                match_result = {
                    'score': score,
                    'matching_skills': matching,
                    'missing_skills': missing,
                    'total_matching': len(matching),
                    'job_total_skills': len(job_set)
                }

                if missing:
                    recommended_courses = get_courses(tuple(missing))


        similar_jobs = []
        try:
            similar_params = {
                'keywords': job.get('jobTitle', ''),
                'resultsToTake': 6
            }
            similar_response = requests.get(
                f"{BASE_URL}/search",
                params=similar_params,
                auth=(API_KEY, ""),
                timeout=10
            )
            similar_data = similar_response.json()
            similar_jobs = [
                j for j in similar_data.get("results", [])
                if j.get("jobId") != job_id
            ][:5]
        except Exception as e:
            print(f"Similar jobs error: {e}")

        job_experience=extract_experience_level(job.get("jobTitle",""))
        experience_warning = None
        if "user" in session:
         user = User.query.filter_by(email=session["user"]).first()
         if user and user.experience_level and job_experience != "Not specified":
          if user.experience_level.lower() not in job_experience.lower():
            experience_warning = f"This role appears to be {job_experience} level. Your profile is set to {user.experience_level}."


        return render_template(
            "job_details.html",job=job,job_skills=job_skills,user_skills=user_skills,match_result=match_result,recommended_courses=recommended_courses,similar_jobs=similar_jobs,job_experience=job_experience,experience_warning=experience_warning)

    except requests.RequestException as e:
        print(f"Error details: {e}")
        return f"Error fetching job details: {e}", 500


def course_matches(course_skills,missing_skills):
    
    for skill in missing_skills:
        if skill.lower() in (course_skills).lower():
            return True
    return False

@cache.memoize(timeout=3600)
def get_courses(missing_skills_tuple):
    
    try:
        df = pd.read_csv('csv/courses.csv')
        matches = df['skills'].apply(course_matches,args=(missing_skills[:10],))
        return df[matches].head(5).to_dict('records')
    except Exception as e:
        print(f"Course error: {e}")
    return []

    
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




def extract_skills_from_description(text: str, skills: list[str]) -> list[str]:
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

    if not allowed_file(file.filename):
        flash("Only PDF files are allowed", "error")
        return redirect(url_for("upload_cv"))

    try:
    
        pdf_bytes = file.read()
        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(pdf_bytes), output, laparams=LAParams())
        cv_text = output.getvalue().lower()
        cv_text = re.sub(r"\s+", " ", cv_text).strip()

        if not cv_text:
            flash("Could not extract text from PDF", "error")
            return redirect(url_for("upload_cv"))

        skills_list = load_skills("csv/skills.csv")
        extracted = extract_skills_from_description(cv_text, skills_list)

        added = 0
        for name in extracted:
            skill = Skill.query.filter_by(name=name).first()
            if not skill:
                skill = Skill(name=name)
                db.session.add(skill)
                db.session.flush()

            exists = UserSkill.query.filter_by(
                user_id=user.id, skill_id=skill.id).first()
            if not exists:
                db.session.add(UserSkill(user_id=user.id, skill_id=skill.id))
                added += 1

        db.session.commit()
        flash(f"Found {len(extracted)} skills, added {added} new", "success")

    except Exception as e:
        print(f"CV error: {e}")
        flash("Error processing CV", "error")

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

@app.route('/forgot_password', methods=["POST", "GET"])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email').strip()
        user = User.query.filter_by(email=email).first()

        if user:
            token = secrets.token_urlsafe(24)
            reset_tokens[token] = email  
            link = url_for('reset_password', token=token, _external=True)
            try:
                msg = Message(
                    subject="Your Password reset link",
                    recipients=[email],
                    body=f"Click the link to reset your password\n{link}\n"
                )
                mail.send(msg)
                flash('Reset link sent to your email', 'success')
            except Exception as e:
                print(f"Mail error: {e}")
                flash('Error sending mail', 'error')
        else:
            flash('If account exists you will receive email link', 'info')
        return redirect(url_for('login_page'))
    return render_template("forgot_password.html")

@app.route('/reset_password/<token>',methods=["POST","GET"])
def reset_password(token):
    email=reset_tokens.get(token)

    if not email:
        flash('Invalid link, please try again','error')
        return redirect(url_for('forgot_password'))
    
    if request.method=='POST':
        password1=request.form.get('password1')
        password2=request.form.get('password2')
    
        if password1 != password2: 
            flash('Passwords do not match', 'error')
            return render_template('reset_password', token=token,email=email)

        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(password1)
            db.session.commit()
            del reset_tokens[token]
            flash('Password updated successfully', 'success')
            return redirect(url_for('login_page'))

    return render_template('reset_password.html', token=token ,email=email)
    

def allowed_file(filename: str) -> bool:   #checks if the uploaded file is a pdf, has to end with .pdf
    return filename.lower().endswith('.pdf')

def normalize_text(s: str) -> str: # converts text into lower case removing and unecessary spaces
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def skill_overlap_score(user_skills: list[str], job_skills: list[str]) -> float:
    userskill = {str(x).strip().lower() for x in user_skills if str(x).strip()}
    jobskill = {str(x).strip().lower() for x in job_skills if str(x).strip()}
    if not jobskill:
        return 0.0
    return (len(userskill & jobskill) / len(jobskill)) * 100.0

def tfidf_cosine_score(user_profile_text: str, job_text: str) -> float:
    user_profile_text = normalize_text(user_profile_text)
    job_text = normalize_text(job_text)
    if not user_profile_text or not job_text:
        return 0.0

    vector = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    X = vector.fit_transform([user_profile_text, job_text])
    sim = cosine_similarity(X[0:1], X[1:2])[0][0] 
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


def extract_experience_level(job_title: str) -> str:  #extracts experience level from job title according to corresponding words
    title = (job_title or "").lower()

    if re.search(r"\b(junior|trainee|entry|graduate|intern|apprentice)\b", title):
        return "Junior"

    elif re.search(r"\b(senior|manager|lead|principal|director|head)\b", title):
        return "Senior"

    elif re.search(r"\b(mid[- ]?level|intermediate)\b", title):
        return "Mid-level"
    else:
        return "Not specified"

@app.route('/logout')
def logout():
    session.pop('user',None)
    flash('Logged out','success')
    return redirect (url_for('home_page'))


@cache.memoize(timeout=200)
def job_fetch(params_tuple):
    params=dict(params_tuple)
    response=requests.get(f"{BASE_URL}/search",params=params,auth=(API_KEY, ""),timeout=10)
    response.raise_for_status()
    return response.json()


@cache.memoize(timeout=600)
def fetch_job(job_id):
    response = requests.get(
        f"{BASE_URL}/jobs/{job_id}",
        auth=(API_KEY, ""),
        timeout=10
    )
    response.raise_for_status()
    return response.json()

@cache.memoize(timeout=3600)
def load_skills(path: str) -> list[str]:
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
@cache.memoize(timeout=200)
def get_scored_jobs(params_tuple, user_skills_tuple, user_profile_text, user_experience, show_all):
    data = job_fetch(params_tuple)
    all_jobs = data.get("results", [])[:50]
    skills_list = load_skills("csv/skills.csv")

    user_skills = list(user_skills_tuple)

    for job in all_jobs:
        desc = job.get("jobDescription", "") or ""
        job_desc_norm = " ".join(str(desc).lower().split())
        job_skills = extract_skills_from_description(job_desc_norm, skills_list)

        skill_score = skill_overlap_score(user_skills, job_skills)
        cosine_score = tfidf_cosine_score(user_profile_text, desc)

        job["match_score"] = final_match_score(skill_score, cosine_score)
        job["experience_level"] = extract_experience_level(job.get("jobTitle", ""))

    all_jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    if user_experience and not show_all:
        aligned_jobs = []
        for job in all_jobs:
            job_exp = job.get("experience_level", "Not specified")
            if job_exp == "Not specified" or user_experience.lower() in job_exp.lower():
                aligned_jobs.append(job)

        aligned_jobs.sort(key=lambda j: (
            0 if user_experience.lower() in j.get("experience_level", "").lower() else 1,
            -j.get("match_score", 0)
        ))

        return aligned_jobs if len(aligned_jobs) >= 5 else all_jobs

    return all_jobs

@cache.memoize(timeout=3600)
def get_courses(missing_skills_tuple):
    missing_skills = list(missing_skills_tuple)
    try:
        df = pd.read_csv('csv/courses.csv')
        matches = df['skills'].apply(course_matches, args=(missing_skills[:10],))
        return df[matches].head(5).to_dict('records')
    except Exception as e:
        print(f"Course error: {e}")
        return []
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404




if __name__ == "__main__":
    app.run(debug=True)
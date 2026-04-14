import unittest
from app import allowed_file,skill_overlap_score,tfidf_cosine_score,extract_skills_from_cv, extract_skills_from_description,is_valid_email, is_valid_password,calculate_match,extract_experience_level

class seeker_test(unittest.TestCase):

    def test_allowed_file(self):
        test_cases =[("johncv.pdf",True),("JOHNCV.PDF",True),("johncv.doc",False)]
        for cases in test_cases:
            text=cases[0]
            output=cases[1]
            self.assertEqual(allowed_file(text),output)
    
    def test_skill_overlap_score(self):
        score = skill_overlap_score(['python','sql'],['python','sql','java','oop'])
        self.assertEqual(score,50)
    
    def test_skill_overlap_score_100(self):
        score = skill_overlap_score(['python','sql','java','oop'],['python','sql','java','oop'])
        self.assertEqual(score,100)

    def test_skill_overlap_score_0(self):
        score = skill_overlap_score(['graphic design'],['python','sql','java','oop'])
        self.assertEqual(score,0)
    
    def test_skill_overlap_score_empty(self):
        score = skill_overlap_score([],['python','sql','java','oop'])
        self.assertEqual(score,0)


    def test_extract_skills_from_description(self):
        cv="experience in python sql java and oop"
        skills_list=["python","sql","java","oop"]
        result=extract_skills_from_description(cv,skills_list)
        self.assertEqual(result,['java', 'oop', 'python', 'sql'])

    def test_tfidf_cosine_score(self):
        score=tfidf_cosine_score("python sql java and oop","python sql java and oop")
        self.assertGreaterEqual(score,100)
    
    def test_tfidf_cosine_score_low_match(self):
        score=tfidf_cosine_score("python sql java and oop","graphic design")
        self.assertLess(score,20)
    


    def test_is_valid_email(self):
        test_cases =[("bob@gmail.com",True),("bob.com",False),("bob",False)]
        for cases in test_cases:
            text=cases[0]
            output=cases[1]
            self.assertEqual(is_valid_email(text),output)
    

    def test_extract_experience_level(self):
        test_cases =[("senior developer","Senior"),("junior developer","Junior"),("software developer","Not specified")]
        for cases in test_cases:
            text=cases[0]
            output=cases[1]
            self.assertEqual(extract_experience_level(text),output)
    
    def test_is_valid_password(self):
        test_cases=[("Password@123","Password@123",True),("password123","password123",False)]

        for password, confirm_password, output in test_cases:
            result = is_valid_password(password, confirm_password)
            self.assertEqual(result[0], output)
            

    def test_calculate_match(self):
        combined_skills=['python','sql','java','oop']
        job_skills=['python','sql','excel','oop']
        profile_text='python sql java data analyst junior'
        job_desc='data analyst with experience in python , sql and excel'
        job_title = 'junior Data Analyst'

        score=calculate_match(combined_skills, profile_text, job_skills, job_desc, job_title)

        self.assertGreaterEqual(score,40)
        self.assertLess(score,100)
        
    


    def test_calculate_low_match(self):
        combined_skills=['teaching ','communication','collaboration']   
        job_skills = ['python', 'sql', 'excel']
        profile_text='teaching communication collaboration teacher'
        job_desc='data analyst with experience in python , sql and excel'
        job_title = 'junior Data Analyst'

        score=calculate_match(combined_skills, profile_text, job_skills, job_desc, job_title)
        self.assertLess(score,20)
    
    
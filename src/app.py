import os
import io
import PyPDF2
import re
import botocore
import boto3
from flask import Flask, render_template, request, Response, redirect, url_for
import ast
import pandas as pd

from helper import get_df_from_csv_in_s3, upload_df_to_s3


app = Flask(__name__)

# Loading configs/global variables
app.config.from_pyfile("config.py")
bucket_name = app.config["BUCKET_NAME"]
mock_data_file = app.config["MOCK_DATA_POC_NAME"]
mock_tasks_data_file = app.config["MOCK_DATA_POC_TASKS"]

# Setting global variables
username = ""
courses = []
emails = ""

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)


# Set up home page for the website
@app.route("/")
def start():
    global username, courses, tasks
    df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
    username = df.loc[0, "username"]  # For PoC purpose
    courses = df.loc[0, "courses"]  # For PoC purpose
    
    # Parsing it into a Python list
    courses = ast.literal_eval(courses)

    tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)
    # Convert the tasks DataFrame to a list of dictionaries
    tasks = tasks_df.groupby('status').apply(lambda x: x.drop('status', axis=1).to_dict(orient='records')).to_dict()

    return render_template(
        "index.html",
        username=username,
        courses=courses,
        current_page='home',
        tasks=tasks
    )


# Download a file from s3
@app.route("/download", methods=["GET"])
def download():
    filename = request.args.get("filename")
    if request.method == "GET":
        # s3_file_path would be different for different types of files, for
        # now use filename as default s3 file path
        s3_file_path = filename
        response = s3.get_object(Bucket=bucket_name, Key=s3_file_path)

        file_content = response["Body"].read()
        headers = {"Content-Disposition": f"attachment; filename={filename}"}

        return Response(file_content, headers=headers)


# Change user's name
@app.route("/change_username", methods=["POST"])
def change_username():
    global username
    if request.method == "POST":
        new_username = request.form["newusername"]
        df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
        df.loc[df["username"] == username, "username"] = new_username
        upload_df_to_s3(df, s3, bucket_name, mock_data_file)
        username = new_username
    return redirect(url_for("start"))


# Remove an existing course
@app.route("/remove_course", methods=["POST"])
def remove_course():
    if request.method == "POST":
        index = request.form["index"]

        df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
        user_courses_serires = df.loc[df["username"] == username, "courses"]
        user_courses_str = user_courses_serires.tolist()[0]
        user_courses = ast.literal_eval(user_courses_str)
        user_courses.pop(int(index))

        list_str = str(user_courses)
        df.loc[df["username"] == username, "courses"] = list_str

        upload_df_to_s3(df, s3, bucket_name, mock_data_file)
    return redirect(url_for("start"))


# Add a new course
@app.route("/add_course", methods=["POST"])
def add_course():
    global username
    if request.method == "POST":
        new_course = request.form["newcourse"]
        df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
        df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)

        user_courses_serires = df.loc[df["username"] == username, "courses"]
        user_courses_str = user_courses_serires.tolist()[0]
        user_courses = ast.literal_eval(user_courses_str)

        user_courses.append(new_course)
        list_str = str(user_courses)
        df.loc[df["username"] == username, "courses"] = list_str

        upload_df_to_s3(df, s3, bucket_name, mock_data_file)
    return redirect(url_for("start"))


# Router to course detailed page
@app.route("/course_page", methods=["GET", "POST"])
def course_page():
    # render the course page, display the course content(name)
    return render_template(
        "course_page.html",
        username=username,
        courses=courses,
        current_page="course_page",
    )


# Router to study plan detailed page
@app.route("/plan_page", methods=["GET", "POST"])
def plan_page():
    # render the plan page
    return render_template(
        "plan_page.html", username=username, current_page="plan_page"
    )


# Router to user profile pageile
@app.route("/profile_page", methods=["GET", "POST"])
def profile_page():
    # render the profile page, showing username on pege
    return render_template(
        "profile_page.html", username=username, current_page="profile_page"
    )


@app.route("/course_detail_page/<course_id>")
def course_detail(course_id):
    # 假设有一个函数check_syllabus_exists()来检测S3中是否有大纲文件
    message = request.args.get("message", "")
    syllabus_exists, syllabus_filename = check_syllabus_exists(course_id)

    if syllabus_exists:
        # 直接调用get_emails路由来提取邮件
        email_list = extract_emails_from_pdf(syllabus_filename)
    else:
        email_list = []

    return render_template(
        "course_detail_page.html",
        course_id=course_id,
        course=course_id,
        username=username,
        email_list=email_list,
        message=message,
    )


def check_syllabus_exists(course_id):
    try:
        # 假设大纲文件的命名规则是：course_id + "-syllabus.pdf"
        syllabus_filename = course_id + "-syllabus.pdf"

        # 检查文件是否存在于S3上
        s3.head_object(Bucket=bucket_name, Key=syllabus_filename)
        return True, syllabus_filename
    except botocore.exceptions.ClientError as e:
        # 如果文件不存在，head_object会抛出ClientError异常
        if e.response["Error"]["Code"] == "404":
            return False, None
        else:
            # 如果出现其他错误，重新抛出异常
            raise e


# input:pdf file
# output: a list of string emails
# extract all the email in the input pdf
@app.route("/get_emails", methods=["GET"])
def extract_emails_from_pdf(filename):
    if request.method == "GET":
        response = s3.get_object(Bucket=bucket_name, Key=filename)
        pdf_file = response["Body"].read()
        pdf_file_obj = io.BytesIO(pdf_file)

        pdf_reader = PyPDF2.PdfReader(pdf_file_obj)
        text = ""

        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text += page.extract_text()

        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"
        emails = re.findall(email_pattern, text)

        return emails


@app.route("/upload/<course_id>", methods=["POST"])
def upload_file(course_id):
    print("course id", course_id)
    if (
        "file" not in request.files
        or not request.files["file"]
        or request.files["file"].filename == ""
    ):
        print("checked")
        return redirect(
            url_for(
                "course_detail",
                course_id=course_id,
                message="No file selected",
                username=username,
            )
        )

    file = request.files["file"]
    new_filename = f"{course_id}-syllabus.pdf"
    file.filename = new_filename  # 更新文件名
    print("file:", file.filename)

    try:
        # 使用 upload_fileobj 方法直接上传
        print("uploading")
        s3.upload_fileobj(
            file, bucket_name, file.filename, ExtraArgs={"ACL": "private"}
        )
        # 确保update_csv函数已经定义
        update_csv(course_id, file.filename)
        print("returning")
        return redirect(
            url_for(
                "course_detail",
                course_id=course_id,
                message="File uploaded successfully!",
                username=username,
            )
        )
    except botocore.exceptions.NoCredentialsError:
        print("error")
        return redirect(
            url_for(
                "course_detail",
                course_id=course_id,
                message="AWS authentication failed. Please check your AWS keys.",
                username=username,
            )
        )


def update_csv(course_id, syllabus_filename):
    csv_file_path = "./poc-data/moc_course_info.csv"  # 更改为实际的文件路径

    # 读取CSV文件，删除空行
    df = pd.read_csv(csv_file_path).dropna(how="all")

    # 检查course_id是否在非空的单元格中
    if course_id in df["course"].dropna().values:
        df.loc[df["course"] == course_id, "course_syllabus"] = syllabus_filename
    else:
        # 创建一个新的DataFrame来添加新行
        new_row = pd.DataFrame(
            {"course": [course_id], "course_syllabus": [syllabus_filename]}
        )
        df = pd.concat([df, new_row], ignore_index=True)

    # 写回CSV文件
    df.to_csv(csv_file_path, index=False)


if __name__ == "__main__":
    app.run(debug=True)

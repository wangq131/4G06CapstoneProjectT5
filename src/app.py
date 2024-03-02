from datetime import datetime, timedelta, timezone
from io import StringIO
import os
import pandas as pd
import botocore
import boto3
import uuid
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    Response,
    redirect,
    url_for,
)
import ast
from sqlalchemy.sql import func
try:
    from helper import (
        check_syllabus_exists,
        update_csv,
        upload_df_to_s3,
        get_df_from_csv_in_s3,
        sql_to_csv_s3,
        initialize_topic_db_from_s3,
        initialize_comment_db_from_s3,
        initialize_user_db_from_s3,
        User,
        Topic,
        Comment,
        db,
        read_order_csv_from_s3,
        write_order_csv_to_s3,
        update_csv_after_deletion,
        extract_text_from_pdf,
        extract_course_work_details,
        process_course_work_with_openai,
        analyze_course_content,
        convert_to_list_of_dicts,
        write_course_work_to_csv,
        process_transcript_pdf,
    )
except ImportError:
    from .helper import (
        check_syllabus_exists,
        update_csv,
        upload_df_to_s3,
        get_df_from_csv_in_s3,
        sql_to_csv_s3,
        initialize_topic_db_from_s3,
        initialize_comment_db_from_s3,
        initialize_user_db_from_s3,
        User,
        Topic,
        Comment,
        db,
        read_order_csv_from_s3,
        write_order_csv_to_s3,
        update_csv_after_deletion,
        extract_text_from_pdf,
        extract_course_work_details,
        process_course_work_with_openai,
        analyze_course_content,
        convert_to_list_of_dicts,
        write_course_work_to_csv,
        process_transcript_pdf,
    )


app = Flask(__name__)
app.secret_key = os.urandom(24)

try:
    from config import MOCK_COURSE_INFO_CSV, COURSE_WORK_EXTRACTED_INFO
except ImportError:
    from .config import MOCK_COURSE_INFO_CSV, COURSE_WORK_EXTRACTED_INFO

# Loading configs/global variables
app.config.from_pyfile("config.py")

# Set the base directory to the directory where app.py is located
basedir = os.path.abspath(os.path.dirname(__file__))
# Set the SQLALCHEMY_DATABASE_URI to point to your project.db file
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    basedir, "instance", "project.db"
)
# app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///project.db"
bucket_name = app.config["BUCKET_NAME"]
mock_data_file = app.config["MOCK_DATA_POC_NAME"]
user_data_file = app.config["USER_DATA_NAME"]
topic_data_file = app.config["TOPIC_DATA_NAME"]
comment_data_file = app.config["COMMENT_DATA_NAME"]
model_file_path = app.config["PRIORITY_MODEL_PATH"]
mock_tasks_data_file = app.config["MOCK_DATA_POC_TASKS"]
Transcript_path = app.config["UPLOAD_FOLDER"]

db.init_app(app)

icon_order_path = app.config["ICON_ORDER_PATH"]
# Setting global variables
username = ""
userId = 1
courses = []
model = None
current_page = "home"
cGPA = "None (Please upload your transcript)"

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)

tomato_data_key = 'weekly_tomato_data.csv'

with app.app_context():
    db.create_all()
    initialize_user_db_from_s3(s3, bucket_name, user_data_file, db)
    initialize_topic_db_from_s3(s3, bucket_name, topic_data_file, db)
    initialize_comment_db_from_s3(s3, bucket_name, comment_data_file, db)


@app.route("/")
def start():
    global username, userId, courses, current_page, tasks
    df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
    username = df.loc[0, "username"]  # For PoC purpose
    courses = df.loc[0, "courses"]  # For PoC purpose
    # Parsing it into a Python list
    courses = ast.literal_eval(courses)
    current_page = "home"
    tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)

    # Replace invalid dates and convert to datetime
    tasks_df["due_date"] = tasks_df["due_date"].replace("0000-00-00", pd.NaT)
    tasks_df["due_date"] = pd.to_datetime(
        tasks_df["due_date"], errors="coerce"
    )

    # Convert the tasks DataFrame to a list of dictionaries
    tasks = (
        tasks_df.groupby("status")
        .apply(lambda x: x.drop("status", axis=1).to_dict(orient="records"))
        .to_dict()
    )
    today = datetime.now().date()
    end_date = today + timedelta(days=21)
    tasks_df["due_date"] = pd.to_datetime(tasks_df["due_date"])
    filtered_tasks = tasks_df[
        (tasks_df["status"].isin(["todo", "in_progress"]))
        & (tasks_df["due_date"] >= pd.Timestamp(today))
        & (tasks_df["due_date"] <= pd.Timestamp(end_date))
    ]

    # Convert due dates to strings in 'YYYY-MM-DD' format
    filtered_tasks["due_date"] = filtered_tasks["due_date"].dt.strftime(
        "%Y-%m-%d"
    )

    # Convert tasks to a list of dictionaries for the frontend
    tasks_for_calendar = filtered_tasks[
        ["title", "course", "due_date"]
    ].to_dict(orient="records")

    c_p = current_page
    return render_template(
        "index.html",
        username=username,
        courses=courses,
        current_page=c_p,
        tasks=tasks,
        tasks_for_calendar=tasks_for_calendar,
    )


@app.route("/get-order")
def get_order():
    df = read_order_csv_from_s3(s3, username, bucket_name, icon_order_path)
    existing_order = df.loc[df["username"] == username, "orders"].iloc[0]
    return jsonify(existing_order)


@app.route("/update-order", methods=["POST"])
def update_order():
    new_orders = request.json

    df = get_df_from_csv_in_s3(s3, bucket_name, icon_order_path)

    if username in df["username"].values:
        df.loc[df["username"] == username, "orders"] = str(new_orders)
    else:
        new_row = pd.DataFrame(
            {"username": [username], "orders": [str(new_orders)]}
        )
        df = pd.concat([df, new_row], ignore_index=True)

    write_order_csv_to_s3(s3, icon_order_path, df, bucket_name)

    return jsonify(
        {"status": "success", "message": "Order updated successfully."}
    )


# Router to feedback bpx page
@app.route("/feedback_page", methods=["GET", "POST"])
def feedback_page():
    global current_page
    current_page = "feedback_page"
    # render the feedback box page
    return render_template(
        "feedback_page.html", username=username, current_page=current_page
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
    global username, current_page, courses
    if request.method == "POST":
        index = request.form["index"]
        df = get_df_from_csv_in_s3(s3, bucket_name, mock_data_file)
        user_courses_series = df.loc[df["username"] == username, "courses"]
        user_courses_str = user_courses_series.tolist()[0]
        user_courses = ast.literal_eval(user_courses_str)

        course_id = user_courses.pop(int(index))

        syllabus_exists, pdf_name = check_syllabus_exists(
            course_id, s3, bucket_name
        )
        if syllabus_exists:
            s3.delete_object(Bucket=bucket_name, Key=pdf_name)
            update_csv_after_deletion(course_id)
        delete_task_by_course(course_id)

        list_str = str(user_courses)
        df.loc[df["username"] == username, "courses"] = list_str
        upload_df_to_s3(df, s3, bucket_name, mock_data_file)
        courses = user_courses
        if current_page == "course_page":
            return render_template(
                "course_page.html",
                username=username,
                courses=courses,
                current_page="course_page",
            )
    return redirect(url_for("start"))


# Add a new course
@app.route("/add_course", methods=["POST"])
def add_course():
    global username, current_page, courses
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
        courses = user_courses
        upload_df_to_s3(df, s3, bucket_name, mock_data_file)

        course_works_df = pd.read_csv(COURSE_WORK_EXTRACTED_INFO)
        course_works = course_works_df[course_works_df["course"] == new_course]

        for index, row in course_works.iterrows():
            course_name = row["course"]
            task_name = row["course_work"]
            due_date = row["due_date"]
            weight = row["score_distribution"]
            est_hours = 3
            add_task_todo(
                course_name, task_name, due_date, str(weight), est_hours
            )

        if current_page == "course_page":
            return render_template(
                "course_page.html",
                username=username,
                courses=courses,
                current_page="course_page",
            )
    return redirect(url_for("start"))


# Router to course page
@app.route("/course_page", methods=["GET", "POST"])
def course_page():
    global courses, current_page
    current_page = "course_page"
    # Render the course page, display the course content(name)
    return render_template(
        "course_page.html",
        username=username,
        courses=courses,
        current_page=current_page,
    )


# Router to user profile pageile
@app.route("/profile_page", methods=["GET", "POST"])
def profile_page():
    global current_page
    current_page = "profile_page"
    # Render the profile page, showing username on pege
    return render_template(
        "profile_page.html",
        username=username,
        current_page=current_page,
        cGPA=cGPA,
    )


# Router to course detail page
@app.route("/course_detail_page/<course_id>")
def course_detail(course_id):
    message = request.args.get("message", "")
    syllabus_exists, pdf_name = check_syllabus_exists(
        course_id, s3, bucket_name
    )

    course_info_df = pd.read_csv(MOCK_COURSE_INFO_CSV)
    course_info_row = course_info_df[course_info_df["course"] == course_id]

    course_works_df = pd.read_csv(COURSE_WORK_EXTRACTED_INFO)
    course_works = course_works_df[course_works_df["course"] == course_id]

    for index, row in course_works.iterrows():
        course_name = row["course"]
        task_name = row["course_work"]
        due_date = row["due_date"]
        weight = row["score_distribution"]
        est_hours = 3
        add_task_todo(course_name, task_name, due_date, str(weight), est_hours)

    return render_template(
        "course_detail_page.html",
        course_id=course_id,
        course=course_id,
        course_info=(
            course_info_row.to_dict(orient="records")[0]
            if not course_info_row.empty
            else None
        ),
        course_works=(
            course_works.to_dict(orient="records")
            if not course_works.empty
            else []
        ),
        message=message,
        username=username,
    )


# Upload the a pdf syllabus file to S3 and extract the course info in the file
@app.route("/upload/<course_id>", methods=["POST"])
def upload_file(course_id):
    if (
        "file" not in request.files
        or not request.files["file"]
        or request.files["file"].filename == ""
    ):
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
    file.filename = new_filename

    try:
        s3.upload_fileobj(
            file, bucket_name, new_filename, ExtraArgs={"ACL": "private"}
        )
        syllabus_exists, pdf_name = check_syllabus_exists(
            course_id, s3, bucket_name
        )
        if syllabus_exists:
            pdf_text = extract_text_from_pdf(pdf_name, bucket_name, s3)
            course_work_details = extract_course_work_details(pdf_text)
            # print(
            #     "!!!!!!!!!course_work_details!!!!!!!!!!: ",
            # course_work_details
            # )
            course_info = analyze_course_content(pdf_text)
            course_work_info = process_course_work_with_openai(
                course_work_details
            )
            # print("!!!!!!!!!course_work_info!!!!!!!!!!: ", course_work_info)
        else:
            course_info = ""
            course_work_info = ""

        update_csv(course_id, file.filename, course_info)
        course_work_list = convert_to_list_of_dicts(course_work_info)
        print("!!!!!!!!!course_work_list!!!!!!!!!!: ", course_work_list)
        write_course_work_to_csv(course_work_list, course_id)

        course_info_df = pd.read_csv(MOCK_COURSE_INFO_CSV)
        course_info_row = course_info_df[course_info_df["course"] == course_id]

        course_works_df = pd.read_csv(COURSE_WORK_EXTRACTED_INFO)
        course_works = course_works_df[course_works_df["course"] == course_id]

        for index, row in course_works.iterrows():
            course_name = row["course"]
            task_name = row["course_work"]
            due_date = row["due_date"]
            weight = row["score_distribution"]
            est_hours = 3
            add_task_todo(
                course_name, task_name, due_date, str(weight), est_hours
            )

        return redirect(
            url_for(
                "course_detail",
                course_id=course_id,
                course_info=(
                    course_info_row.to_dict(orient="records")[0]
                    if not course_info_row.empty
                    else None
                ),
                course_works=(
                    course_works.to_dict(orient="records")
                    if not course_works.empty
                    else []
                ),
                message="File uploaded successfully!",
                username=username,
            )
        )
    except botocore.exceptions.NoCredentialsError:
        return redirect(
            url_for(
                "course_detail",
                course_id=course_id,
                message="AWS authentication failed. Check your AWS keys.",
                username=username,
            )
        )


# Router to forum page
@app.route("/forum_page", methods=["GET", "POST"])
def forum_page():
    global current_page
    current_page = "forum_page"

    # Subquery to count comments for each topic
    comment_count_subquery = (
        db.session.query(
            Comment.topicId, func.count(Comment.id).label("comment_count")
        )
        .group_by(Comment.topicId)
        .subquery()
    )

    # Modify your existing query to include the comment count
    topics_with_comment_count = (
        db.session.query(
            Topic, User.username, comment_count_subquery.c.comment_count
        )
        .outerjoin(
            comment_count_subquery,
            Topic.id == comment_count_subquery.c.topicId,
        )
        .join(User, Topic.userId == User.userId)
        .all()
    )
    return render_template(
        "forum_page.html",
        topics=topics_with_comment_count,
        current_page=current_page,
        username=username,
    )


@app.route("/add_topic", methods=["GET", "POST"])
def add_topic():
    global current_page
    current_page = "forum_page"
    if request.method == "POST":
        # Process the form data and add the new topic
        title = request.form["title"]
        description = request.form["description"]
        # Assume 'userId' is obtained from the session or a decorator
        topic = Topic(title=title, description=description, userId=userId)
        db.session.add(topic)
        db.session.commit()
        sql_to_csv_s3("topic", s3, bucket_name, topic_data_file)
        # Redirect to the forum page after adding the topic
        return redirect(url_for("forum_page"))
    # Render the add topic form if method is GET

    return render_template(
        "add_topic_page.html",
        current_page=current_page,
        username=username,
    )


@app.route("/forum/topic/<int:id>", methods=["GET", "POST"])
def topic(id):
    global current_page
    current_page = "forum_page"
    if request.method == "POST":
        # Add a new comment to the topic
        # print("Current usser id: ", userId)
        comment = Comment(
            text=request.form["comment"], topicId=id, userId=userId
        )
        db.session.add(comment)
        db.session.commit()
        sql_to_csv_s3("comment", s3, bucket_name, comment_data_file)

    # pull the topic and comments
    topic_with_user = (
        db.session.query(Topic, User.username)
        .join(User, Topic.userId == User.userId)
        .filter(Topic.id == id)
        .first_or_404()
    )

    topic, author_username = topic_with_user

    # Correct the query here to filter comments by topic.id
    comments_with_users = (
        db.session.query(Comment, User.username)
        .join(User, Comment.userId == User.userId)
        .filter(Comment.topicId == id)  # Filter by topic ID
        .all()
    )
    return render_template(
        "forum_topic_page.html",
        topic=topic,
        comments=comments_with_users,  # Pass the filtered comments
        author_username=author_username,
        current_page=current_page,
        username=username,
    )


@app.route("/search_forum")
def search():
    global current_page
    current_page = "forum_page"
    query = request.args.get("query", "")

    # Naive matching from topics
    matching_topics = Topic.query.filter(
        Topic.title.contains(query) | Topic.description.contains(query)
    ).all()

    # Naive matching from comments
    matching_comments = Comment.query.filter(
        Comment.text.contains(query)
    ).all()

    # Combine the results
    results = {"topics": matching_topics, "comments": matching_comments}

    # Render a template with the search results
    return render_template(
        "search_forum_results.html",
        results=results,
        query=query,
        userId=userId,
        current_page=current_page,
        username=username,
    )


# update tasks status after dragging
@app.route("/update_task_status", methods=["POST"])
def update_task_status():
    data = request.get_json()

    try:
        task_id = int(data["id"])
    except ValueError:
        return jsonify({"message": "Invalid task ID format"}), 400
    new_status = data["status"]

    tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)
    if task_id in tasks_df["id"].tolist():
        tasks_df.loc[tasks_df["id"] == task_id, "status"] = new_status
        csv_buffer = StringIO()
        tasks_df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        s3.put_object(
            Bucket=bucket_name,
            Key=mock_tasks_data_file,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv",
        )
        return jsonify({"message": "Task status updated successfully"})
    else:
        return jsonify({"message": "Task not found"}), 404


def add_task_todo(course_name, task_name, due_date, weight, est_hours):
    # 检查 due_date 是否是有效的日期格式
    try:
        # 尝试将 due_date 解析为 datetime 对象
        if due_date not in ["", "Not Found", "0"]:
            due_date_obj = datetime.strptime(due_date, "%Y-%m-%d")
            days_until_due = (due_date_obj - datetime.now()).days
            # 根据截止日期距今天数设置任务优先级
            priority = "high" if days_until_due < 7 else "low"
        else:
            # 对于无效的 due_date，将其设置为特殊值，并标记优先级为 "unknown"
            due_date = "0000-00-00"
            priority = "unknown"
    except ValueError:
        # 如果 due_date 格式不正确，也将其设置为特殊值，并标记优先级为 "unknown"
        due_date = "0000-00-00"
        priority = "unknown"

    tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)

    new_task = {
        "id": tasks_df["id"].max() + 1 if not tasks_df.empty else 1,
        "title": task_name,
        "course": course_name,
        "due_date": due_date,
        "weight": weight,
        "est_time": est_hours,
        "priority": priority,
        "status": "todo",
    }
    new_task_df = pd.DataFrame([new_task])
    tasks_df = pd.concat([tasks_df, new_task_df], ignore_index=True)

    csv_buffer = StringIO()
    tasks_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    s3.put_object(
        Bucket=bucket_name,
        Key=mock_tasks_data_file,
        Body=csv_buffer.getvalue(),
        ContentType="text/csv",
    )


def delete_task_by_course(course_name):
    try:
        tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)
        if course_name in tasks_df["course"].values:
            tasks_df = tasks_df[tasks_df["course"] != course_name]
            csv_buffer = StringIO()
            tasks_df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)
            s3.put_object(
                Bucket=bucket_name,
                Key=mock_tasks_data_file,
                Body=csv_buffer.getvalue(),
                ContentType="text/csv",
            )
            return jsonify({"message": "Task deleted successfully"}), 200
        else:
            return jsonify({"message": "Task not found"}), 404
    except Exception as e:
        print(f"An error occurred: {e}")
        return (
            jsonify({"message": "An error occurred while deleting the task"}),
            500,
        )


@app.route("/add_task", methods=["POST"])
def add_task():
    course_name = request.form.get("course_name")
    task_name = request.form.get("task_name")
    due_date = request.form.get("due_date")
    weight = request.form.get("weight", 0)
    est_hours = request.form.get("est_hours", 0)

    add_task_todo(course_name, task_name, due_date, weight, est_hours)
    return redirect(url_for("start"))


@app.route("/delete_task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    try:
        tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)
        if task_id in tasks_df["id"].values:
            tasks_df = tasks_df[tasks_df["id"] != task_id]
            csv_buffer = StringIO()
            tasks_df.to_csv(csv_buffer, index=False)
            csv_buffer.seek(0)
            s3.put_object(
                Bucket=bucket_name,
                Key=mock_tasks_data_file,
                Body=csv_buffer.getvalue(),
                ContentType="text/csv",
            )
            return jsonify({"message": "Task deleted successfully"}), 200
        else:
            return jsonify({"message": "Task not found"}), 404
    except Exception as e:
        print(f"An error occurred: {e}")
        return (
            jsonify({"message": "An error occurred while deleting the task"}),
            500,
        )


@app.route("/edit_task/<int:task_id>", methods=["POST"])
def edit_task(task_id):
    tasks_df = get_df_from_csv_in_s3(s3, bucket_name, mock_tasks_data_file)

    existing_task = tasks_df.loc[tasks_df["id"] == task_id].iloc[0]
    new_course_name = request.form.get("course_name")
    new_task_name = request.form.get("task_name")
    new_due_date_str = request.form.get("due_date")
    new_weight = request.form.get("weight")
    new_est_hours = request.form.get("est_hours")

    if new_due_date_str:
        new_due_date = datetime.strptime(new_due_date_str, "%Y-%m-%d").date()
        days_until_due = (new_due_date - datetime.now().date()).days
        new_priority = "high" if days_until_due < 7 else "low"
        formatted_due_date = new_due_date.strftime("%Y-%m-%d")
    else:
        formatted_due_date = existing_task["due_date"]
        new_priority = existing_task["priority"]

    if task_id not in tasks_df["id"].values:
        return jsonify({"message": "Task not found"}), 404

    try:
        task_index = tasks_df.index[tasks_df["id"] == task_id].tolist()[0]
        tasks_df.at[task_index, "course"] = new_course_name
        tasks_df.at[task_index, "title"] = new_task_name
        tasks_df.at[task_index, "due_date"] = formatted_due_date
        tasks_df.at[task_index, "weight"] = new_weight
        tasks_df.at[task_index, "est_time"] = new_est_hours
        tasks_df.at[task_index, "priority"] = new_priority

        csv_buffer = StringIO()
        tasks_df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        s3.put_object(
            Bucket=bucket_name,
            Key=mock_tasks_data_file,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv",
        )
        return jsonify({"message": "Task updated successfully"}), 200
    except Exception as e:
        print(f"An error occurred when updating task: {e}")
        return (
            jsonify({"message": "An error occurred while updating the task"}),
            500,
        )


# Store the feedback to our s3
@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    if request.method == "POST":
        name = request.form.get("name", default=None)
        email = request.form.get("email", default=None)
        feedback_type = request.form["feedback_type"]
        feedback = request.form["feedback"]

        feedback_id = str(uuid.uuid4())

        feedback_data = {
            "feedback_id": [feedback_id],
            "name": [name],
            "email": [email],
            "feedback_type": [feedback_type],
            "feedback": [feedback],
        }
        new_feedback_df = pd.DataFrame(feedback_data)

        feedback_data_path = "feedback.csv"

        try:
            response = s3.get_object(
                Bucket=bucket_name, Key=feedback_data_path
            )
            feedback_df = pd.read_csv(response["Body"])
        except s3.exceptions.NoSuchKey:
            feedback_df = pd.DataFrame(
                columns=[
                    "feedback_id",
                    "name",
                    "email",
                    "feedback_type",
                    "feedback",
                ]
            )

        feedback_df = pd.concat(
            [feedback_df, new_feedback_df], ignore_index=True
        )
        new_csv_file_path = "poc-data/tmp.csv"
        feedback_df.to_csv(new_csv_file_path, index=False)
        s3.upload_file(
            new_csv_file_path,
            bucket_name,
            feedback_data_path,
        )
        os.remove(new_csv_file_path)

    return redirect(url_for("feedback_page"))


# Router to pomodoro page
@app.route("/pomodoro_page", methods=["GET", "POST"])
def pomodoro_page():
    est_time = request.args.get('est_time', default=None)
    global current_page
    current_page = "pomodoro_page"
    # Render the profile page, showing username on pege
    return render_template(
        "pomodoro_page.html", username=username, current_page=current_page,
        est_time=est_time
    )


@app.route("/upload_transcript", methods=["GET", "POST"])
def upload_transcript():
    if request.method == "POST":
        file = request.files["transcript"]
        os.makedirs(Transcript_path, exist_ok=True)
        if file:
            filename = file.filename
            file.save(os.path.join(Transcript_path, filename))
            global cGPA
            cGPA = process_transcript_pdf(
                os.path.join(Transcript_path, filename)
            )
            cGPA = f"{cGPA}/12 ({cGPA/3}/4)"
            return render_template(
                "profile_page.html",
                username=username,
                current_page=current_page,
                cGPA=cGPA,
            )

    # If it's a GET request, just render the upload form
    return render_template(
        "profile_page.html",
        username=username,
        current_page=current_page,
        cGPA=cGPA,
    )


def write_df_to_csv_in_s3(client, bucket, key, dataframe):
    csv_buffer = StringIO()
    dataframe.to_csv(csv_buffer, index=False)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_buffer.getvalue(),
        ContentType='text/csv'
    )


# Update Tomato count for weekly achievements form
@app.route('/update_tomato/<day>', methods=['POST'])
def update_tomato(day):
    utc_now = datetime.now(timezone.utc)
    current_week = utc_now.isocalendar()[1]

    try:
        # Load existing data or initialize if not present
        try:
            tomato_df = get_df_from_csv_in_s3(s3, bucket_name, tomato_data_key)
            # Check if it's a new week
            if tomato_df['week_of_year'].iloc[0] != current_week:
                tomato_df['count'] = 0
                tomato_df['week_of_year'] = current_week
        except s3.exceptions.NoSuchKey:
            tomato_df = pd.DataFrame({
                'day': [
                    'Saturday', 'Sunday', 'Monday', 'Tuesday', 'Wednesday',
                    'Thursday', 'Friday'
                ],
                'count': [0, 0, 0, 0, 0, 0, 0],
                'week_of_year': [current_week] * 7
            })

        # Update count for the specified day
        if day in tomato_df['day'].values:
            tomato_df.loc[tomato_df['day'] == day, 'count'] += 1
            write_df_to_csv_in_s3(s3, bucket_name, tomato_data_key, tomato_df)
            return jsonify({"message": "Tomato count updated successfully"})
        else:
            return jsonify({"message": "Invalid day"}), 400

    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify(
            {"message": "An error occurred while updating tomato count"}
        ), 500


# Initialize the weekly data for no record for this week
def initialize_weekly_data():
    # Initialize the weekly data for each day to zero
    days = ['Saturday', 'Sunday', 'Monday', 'Tuesday', 'Wednesday',
            'Thursday', 'Friday']
    week_of_year = datetime.now().isocalendar()[1]
    data = {'day': days, 'count': [0]*7, 'week_of_year': [week_of_year]*7}
    return pd.DataFrame(data)


# Router for getting weekly data from s3
@app.route('/get_weekly_data', methods=['GET'])
def get_weekly_data():
    utc_now = datetime.now(timezone.utc)
    current_week = utc_now.isocalendar()[1]
    tomato_df = get_df_from_csv_in_s3(s3, bucket_name, tomato_data_key)
    if tomato_df['week_of_year'].iloc[0] != current_week:
        # Reset the weekly data since it's a new week
        tomato_df = initialize_weekly_data()
        write_df_to_csv_in_s3(s3, bucket_name, tomato_data_key, tomato_df)
    # Convert DataFrame to JSON response
    return jsonify(tomato_df.to_dict(orient='records'))


if __name__ == "__main__":
    app.run(debug=True)

# A configuration file where all constants are defined
BUCKET_NAME = "course-buddy"
MOCK_DATA_POC_NAME = "mock_data_poc.csv"
USER_DATA_NAME = "user_data.csv"
TOPIC_DATA_NAME = "topic_data.csv"
COMMENT_DATA_NAME = "comment_data.csv"
PRIORITY_MODEL_FILE_NAME = "trained_priority_model.joblib"
PRIORITY_MODEL_FILE_PATH = (
    f"src/task_priority_training_pipeline/{PRIORITY_MODEL_FILE_NAME}"
)
PRIORITY_MODEL_PATH = f"model/{PRIORITY_MODEL_FILE_NAME}"
MOCK_COURSE_INFO_CSV = "./poc-data/mock_course_info.csv"
MOCK_DATA_POC_TASKS = "mock_data_tasks.csv"
SQLALCHEMY_DATABASE_URI = "sqlite:///project.db"
TEMPLATES_AUTO_RELOAD = True

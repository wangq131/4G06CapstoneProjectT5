import ast
import pandas as pd
import pytest
from unittest.mock import patch, ANY, MagicMock
from src.app import app
import sys
import os
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            '../src')))

# Test cases generated by: OpenAI. (2023). ChatGPT
# [Large language model]. https://chat.openai.com


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@patch('src.app.s3')
def test_download(mock_s3, client):
    # Set up a mock response for s3.get_object
    mock_file_content = b'file content'
    mock_s3.get_object.return_value = {
        'Body': MagicMock(read=MagicMock(return_value=mock_file_content))
    }

    # Test file name
    test_filename = 'testfile.txt'

    # Perform the test request
    response = client.get(f'/download?filename={test_filename}')

    # Assertions
    assert response.status_code == 200
    assert response.data == mock_file_content
    assert response.headers[
        "Content-Disposition"] == f"attachment; filename={test_filename}"
    mock_s3.get_object.assert_called_once_with(
        Bucket=app.config["BUCKET_NAME"], Key=test_filename)


@patch('src.app.upload_df_to_s3')
@patch('src.app.get_df_from_csv_in_s3')
# Directly set the username to 'test_user'
@patch('src.app.username', 'test_user')
def test_change_username(mock_get_df, mock_upload_df, client):
    initial_username = 'old_user'
    new_username = 'new_user'

    # Mock DataFrame setup
    mock_df = pd.DataFrame(
        {'username': [initial_username], 'courses': ['course1, course2']})
    mock_get_df.return_value = mock_df

    # Perform the test request
    response = client.post(
        '/change_username',
        data={
            'newusername': new_username})

    # Assertions
    assert response.status_code == 302
    mock_get_df.assert_called_once_with(ANY, ANY, ANY)
    mock_upload_df.assert_called_once_with(mock_df, ANY, ANY, ANY)


@patch('src.app.upload_df_to_s3')
@patch('src.app.get_df_from_csv_in_s3')
@patch('src.app.username', 'test_user')
def test_remove_course(mock_get_df, mock_upload_df, client):

    # Mock DataFrame setup
    initial_courses = ['course1', 'course2', 'course3']
    mock_df = pd.DataFrame(
        {'username': ['test_user'], 'courses': [str(initial_courses)]})
    mock_get_df.return_value = mock_df

    # Index of the course to be removed
    index_to_remove = 1

    # Perform the test request
    response = client.post('/remove_course',
                           data={'index': str(index_to_remove)})

    # Assertions
    assert response.status_code == 302
    mock_get_df.assert_called_once_with(
        ANY, ANY, ANY)
    mock_upload_df.assert_called_once_with(ANY, ANY, ANY, ANY)

    # Additional check to ensure the course is removed
    updated_courses_str = mock_df.loc[mock_df['username']
                                      == 'test_user', 'courses'].iloc[0]
    updated_courses = ast.literal_eval(updated_courses_str)
    assert len(updated_courses) == len(initial_courses) - 1


@patch('src.app.upload_df_to_s3')
@patch('src.app.get_df_from_csv_in_s3')
# Directly set the username to 'test_user'
@patch('src.app.username', 'test_user')
def test_add_course(mock_get_df, mock_upload_df, client):
    # Mock DataFrame setup
    initial_courses = ['course1', 'course2']
    mock_df = pd.DataFrame(
        {'username': ['test_user'], 'courses': [str(initial_courses)]})
    mock_get_df.return_value = mock_df

    # New course to add
    new_course = 'new_course'

    # Perform the test request
    response = client.post('/add_course', data={'newcourse': new_course})

    # Assertions
    assert response.status_code == 302
    assert mock_get_df.call_count == 2  # Expecting two calls
    # Checking the parameters of the last call
    mock_get_df.assert_called_with(ANY, ANY, ANY)
    mock_upload_df.assert_called_once_with(mock_df, ANY, ANY, ANY)


@patch('src.app.username', new_callable=lambda: 'test_user')
@patch('src.app.courses', new_callable=lambda: ['course1', 'course2'])
def test_course_page(mock_username, mock_courses, client):
    # Perform the test request
    response = client.get('/course_page')

    # Assertions
    assert response.status_code == 200
    assert 'text/html' in response.content_type
    data = response.data.decode('utf-8')
    assert 'course-list' in data
    assert 'course1' in data
    assert 'course2' in data


@patch('src.app.username', new_callable=lambda: 'test_user')
def test_plan_page(mock_username, client):
    # Perform the test request
    response = client.get('/plan_page')

    # Assertions
    assert response.status_code == 200
    assert 'text/html' in response.content_type
    data = response.data.decode('utf-8')
    assert 'This is plan page!!!' in data


@patch('src.app.username', new_callable=lambda: 'test_user')
def test_profile_page(mock_username, client):
    # Perform the test request
    response = client.get('/profile_page')

    # Assertions
    assert response.status_code == 200
    assert 'text/html' in response.content_type
    data = response.data.decode('utf-8')
    assert '/change_username' in data

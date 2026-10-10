"""A project's mailbox is named as its folder is; a public repository's outer folder ends in
-code, which is dropped."""
from lobstertools import mail


def test_project_name_is_the_folder_name_without_a_code_suffix():
    assert mail.project_name("/Users/s/projects/code/video-tools") == "video-tools"
    assert mail.project_name("/Users/s/projects/code/lobster-tools-code") == "lobster-tools"
    assert mail.project_name("/Users/s/projects/non-code/training-video/") == "training-video"
    assert mail.project_name("relative/folder-code/") == "folder"

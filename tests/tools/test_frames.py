from study_notes.tools.frames import frame_filename


def test_frame_filename_slugifies_timestamp():
    assert frame_filename("raft", "00:14:32") == "raft_00-14-32.jpg"

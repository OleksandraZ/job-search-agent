# Shared by munich_local.py and germany_remote.py: main.py fetches once via the union
# of both agents' SOURCE_IDS rather than calling each agent's run() separately (which
# would double the request volume) - that only avoids doubling request volume if both
# agents actually draw from the same source list.
SOURCE_IDS = [
    "arbeitnow_qa_jobs",
    "germantechjobs_testing_germany",
    "stepstone_germany",
    "devjobs_germany_qa_engineer",
    "testdevjobs_remote_germany",
    "wearedevelopers_jobs",
    "englishjobsde",
    "built_in_qa_germany",
    "xing_jobs",
    "get_in_it",
    "instaffo_qa_engineer",
    "bundesagentur_für_arbeit_jobsuche",
]

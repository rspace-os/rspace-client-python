#!/usr/bin/env python3

import re
import time

import rspace_client


def print_users(response):
    print("Users in response:")
    with open("toDelete-8087.txt", "a+") as toDelete:
        for user in response["users"]:
            print(user["id"])
            toDelete.write(f"{user['id']}\n")
        toDelete.close()


def delete_users():
    failedIds = []
    with open("log-delete.txt", "r+") as deletelog:
        lines = deletelog.readlines()
        for line in lines:
            if re.match("^FAILED", line):
                failedId = line.split(sep=" ")[1]
                failedIds.append(failedId.rstrip("\r\n"))
    print(f"Will ignore these userids that are known to fail: {failedIds}")

    with (
        open("toDelete-8087.txt") as toDelete,
        open("log-delete.txt", "a+") as deletelog,
    ):
        lines = toDelete.readlines()
        for line in lines:
            userId = line.rstrip("\r\n")
            if userId in failedIds:
                print(f"Id {userId} has previously failed, skipping")
                continue
            print(f"Deleting user {userId}")
            try:
                resp = client.deleteTempUser(userId)
                if resp.status_code == 204:
                    deletelog.write(f"Deleted {userId}\n")
                    deletelog.flush()
                    print(f"Deleted {userId}\n")
            except Exception:
                deletelog.write(f"FAILED {userId}\n")
                deletelog.flush()
                print(f"FAILED {userId}\n")
                time.sleep(1)
        print("Finished")
        deletelog.close()


# Parse command line parameters
client = rspace_client.utils.createELNClient()

# Simple search
response = client.get_users(
    page_size=50,
    tempaccount_only=False,
    last_login_before="2022-01-01",
    created_before="2022-01-01",
)
print_users(response)


while client.link_exists(response, "next"):
    time.sleep(1)
    print("Retrieving next page...")
    response = client.get_link_contents(response, "next")
    print_users(response)

delete_users()

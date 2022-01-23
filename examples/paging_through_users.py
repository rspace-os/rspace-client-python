#!/usr/bin/env python3

from __future__ import print_function
import rspace_client
import time
import re


def print_users(response):
    print("Users in response:")
    with open("toDelete-8087.txt", "a+") as toDelete:
        for user in response["users"]:
            print(user["id"])
            toDelete.write("{0}\n".format(user["id"]))
        toDelete.close()


def delete_users():
    failedIds = []
    with open("log-delete.txt", "r+") as deletelog:
        lines = deletelog.readlines()
        for line in lines:
            if re.match("^FAILED", line):
                failedId = line.split(sep=" ")[1]
                failedIds.append(failedId.rstrip("\r\n"))
    print("Will ignore these userids that are known to fail: {}".format(failedIds))

    with open("toDelete-8087.txt", "r") as toDelete, open(
        "log-delete.txt", "a+"
    ) as deletelog:
        lines = toDelete.readlines()
        for line in lines:
            userId = line.rstrip("\r\n")
            if userId in failedIds:
                print("Id {} has previously failed, skipping".format(userId))
                continue
            print("Deleting user {}".format(userId))
            try:
                resp = client.deleteTempUser(userId)
                if resp.status_code == 204:
                    deletelog.write("Deleted {0}\n".format(userId))
                    deletelog.flush()
                    print("Deleted {}\n".format(userId))
            except:
                deletelog.write("FAILED {0}\n".format(userId))
                deletelog.flush()
                print("FAILED {}\n".format(userId))
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

#!/usr/bin/env python3

from __future__ import print_function
import rspace_client
import time

def print_users(response):
    print('Users in response:')
    with open("toDelete-8087.txt", 'a+') as toDelete:     
        for user in response['users']:
            print(user['id']) 
            toDelete.write("{0}\n".format(user['id']))
            
def delete_users(): 
    with open("toDelete-8087.txt", "r") as toDelete:
        with open("log-8087.txt", "a+") as log:
            lines = toDelete.readlines()
            for line in lines:
                userId = line.rstrip("\r\n")
                print("Deleting user {}".format(userId))
                try:
                    resp = client.deleteTempUser(userId)
                    if resp.status_code == 204:
                        log.write("Deleted {}\n".format(userId))
                        print ("Deleted {}\n".format(userId))
                except:
                    log.write("FAILED {}\n".format(userId))
                    print ("FAILED {}\n".format(userId))
                time.sleep(1)
            print ("Finished")

# Parse command line parameters
client = rspace_client.utils.createClient()

#Simple search
response = client.get_users(page_size=50,tempaccount_only="false", last_login_before="2017-05-01",  created_before="2017-05-01")
print_users(response)
     
 
while client.link_exists(response, 'next'):
    time.sleep(1)
    print('Retrieving next page...')
    response = client.get_link_contents(response, 'next')
    print_users(response)

delete_users()


        
    
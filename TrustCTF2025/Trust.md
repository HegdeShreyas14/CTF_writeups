# IIT Bombay TrustLab CTF writeups


![alt text](images/zap.png)

## N00b Randomness
###


## Secure API 
###


## Breached
### Description

```
The email of the admin of Acme surveys has been breached in a recent data leak. However, no-one, not even the Acme employees know who is the admin of Acme. Fortunately, the generous developers of HaveIBeenChowned have provided us with an endpoint at https://tlctf2025-hibc.chals.io/ to help us with our quest.

Your task should you choose to accept it is to figure out the secret of the admin.
```

The link to the website was also given along with this along with files needed for running the website locally.A .env file was provided which contained FLAG_SECRET and ADMIN_API_KEY.  
A csv file was also provided which contained all the email addresses of employees of the company.  


- On going to the API endpoint given, we find 
![alt text](images/breached.png)

- On entering email addresses we get to know if the provided address was a part of the data leak or not.
- The email addressed of employees can be found in the csv file which was uploaded.
- The server.py file provided helps in understanding how the server functions on the backend of the website.
- The challenge uses HMAC( Hash Based Message Authentication Code) which takes a key and a message.If the key is unknown then we can not forge the HMAC.  
The code snippet given :
```py
token_for_email(email) = HMAC_SHA256(FLAG_SECRET, email)
if hmac.compare_digest(token_for_email(email), FLAG_TOKEN):
    matched = True
```
From this we understand that the generated hash is computed with a FLAG_TOKEN which exists in the system.  

From the premise of the question it is clear that the FLAG_TOKEN is generated from the admin of the organisation.

So now we have to find the email which was part of the data breach.  
- There are 499 emails given, we gmake a script which  bruteforces all the emails at the API endpoint given, when the **pwned** value turns true we know that it was involved in the breach and is the admin's email.

The script used was 
```py



```

- From this we find that the admin email was blake.baker20@acme.test . Using this email and generating the hash for this, we can log into the website where the flag is displayed.

### Flag:
`trustctf{aefefb18de55}`




## Telegrammatic Induction
- Introductory flag, provided directly in the telegram group

### Flag:
`trustctf{l3t_th3_g4me5_b3g1n_ar3_y0u_r34dy_f0r_1t?}`



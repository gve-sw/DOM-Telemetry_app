# set base image
FROM python:3.8

# set the working directory in the container
WORKDIR /usr/src/app

# copy the dependencies file to the working directory
COPY requirements.txt .

# install dependencies
RUN pip install -r requirements.txt
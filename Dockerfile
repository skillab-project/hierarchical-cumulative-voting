# Use an official Python runtime as a parent image
FROM python:3.9

# Set the working directory inside the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Create the folder for the ESCO xls file
RUN mkdir -p /app/Completed_Analyses

# Copy the Excel file into the Completed_Analyses folder
COPY new_ESCO_mapping.xlsx /app/Completed_Analyses/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port FastAPI will run on
EXPOSE 8000

# Run the FastAPI application using Uvicorn
CMD ["uvicorn", "HCV:app", "--host", "0.0.0.0", "--port", "8000"]

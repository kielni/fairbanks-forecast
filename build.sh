docker build -t fairbanks-forecast .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $AWS_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker tag fairbanks-forecast:latest $AWS_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fairbanks-forecast:latest
docker push $AWS_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fairbanks-forecast:latest
aws lambda update-function-code --function-name fairbanks-forecast --image-uri $AWS_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/fairbanks-forecast:latest

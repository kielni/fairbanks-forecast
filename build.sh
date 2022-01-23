NAME="fairbanks-forecast"
ECR_URL="$AWS_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com"

docker build -t $NAME .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_URL
docker tag $NAME:latest $ECR_URL/$NAME:latest
docker push $ECR_URL/$NAME:latest
aws lambda update-function-code --function-name $NAME --image-uri $ECR_URL/$NAME:latest

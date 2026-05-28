import boto3
from datetime import datetime, timedelta, timezone

# AWS Clients
ec2 = boto3.client('ec2')
cloudwatch = boto3.client('cloudwatch')
sns = boto3.client('sns')

# CONFIGURATION
CPU_THRESHOLD = 5.0
DAYS_TO_CHECK = 7
DRY_RUN = True

# SNS Topic ARN
SNS_TOPIC_ARN = 'YOUR_SNS_TOPIC_ARN'


def lambda_handler(event, context):

    print("Starting EC2 Optimization Scan")

    reservations = ec2.describe_instances()['Reservations']

    for reservation in reservations:

        for instance in reservation['Instances']:

            instance_id = instance['InstanceId']
            instance_type = instance['InstanceType']
            state = instance['State']['Name']

            # Only running instances
            if state != 'running':
                continue

            # Read Tags
            tags = instance.get('Tags', [])

            tag_dict = {
                t['Key']: t['Value']
                for t in tags
            }

            # Skip if AutoStop not enabled
            if tag_dict.get('AutoStop') != 'true':
                print(f"Skipping {instance_id} (AutoStop not enabled)")
                continue

            # Skip production instances
            if tag_dict.get('Environment') == 'Production':
                print(f"Skipping Production Instance {instance_id}")
                continue

            # Time Range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=DAYS_TO_CHECK)

            # Get CPU Metrics
            metrics = cloudwatch.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[
                    {
                        'Name': 'InstanceId',
                        'Value': instance_id
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Average']
            )

            datapoints = metrics['Datapoints']

            if not datapoints:
                print(f"No metrics found for {instance_id}")
                continue

            # Average CPU
            avg_cpu = sum(
                d['Average']
                for d in datapoints
            ) / len(datapoints)

            print(
                f"Instance: {instance_id} | "
                f"Type: {instance_type} | "
                f"Avg CPU: {avg_cpu:.2f}%"
            )

            # -------------------------------------------------
            # FEATURE 1 — AUTO STOP IDLE EC2
            # -------------------------------------------------

            if avg_cpu < CPU_THRESHOLD:

                message = (
                    f"Idle EC2 Detected\n\n"
                    f"Instance ID: {instance_id}\n"
                    f"Instance Type: {instance_type}\n"
                    f"Average CPU: {avg_cpu:.2f}%\n\n"
                    f"Action: Stop Instance"
                )

                print(message)

                # SNS Notification
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject='EC2 Idle Instance Alert',
                    Message=message
                )

                # DRY RUN
                if DRY_RUN:
                    print(
                        f"[DRY RUN] Would stop "
                        f"{instance_id}"
                    )

                else:
                    ec2.stop_instances(
                        InstanceIds=[instance_id]
                    )

                    print(
                        f"Stopped instance "
                        f"{instance_id}"
                    )

            # -------------------------------------------------
            # FEATURE 2 — UNDERUTILIZED EC2 DETECTION
            # -------------------------------------------------

            recommendation = None

            if (
                instance_type == 't3.large'
                and avg_cpu < 5
            ):
                recommendation = 't3.micro'

            elif (
                instance_type == 't3.medium'
                and avg_cpu < 10
            ):
                recommendation = 't3.small'

            elif (
                instance_type == 't3.xlarge'
                and avg_cpu < 10
            ):
                recommendation = 't3.medium'

            # Recommendation Notification
            if recommendation:

                recommendation_message = (
                    f"Underutilized EC2 Detected\n\n"
                    f"Instance ID: {instance_id}\n"
                    f"Current Type: {instance_type}\n"
                    f"Average CPU: {avg_cpu:.2f}%\n\n"
                    f"Recommended Type: {recommendation}"
                )

                print(recommendation_message)

                sns.publish(
                    TopicArn=SNS_TOPIC_ARN, # Add you SNS ARN
                    Subject='EC2 Rightsizing Recommendation',
                    Message=recommendation_message
                )

    return {
        'statusCode': 200,
        'body': 'EC2 Optimization Completed'
    }

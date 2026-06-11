import * as path from 'path';
import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as sfnTasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import { Construct } from 'constructs';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const ASSET_EXCLUDES = [
  'cdk.out', 'infra', '.git', '**/__pycache__', '*.pyc', '.venv',
  'venv', 'node_modules', 'tests', 'docs', 'experiments', 'frontend',
  '.DS_Store', '*.egg-info',
];

export class SarathiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ─── DynamoDB: single table ───────────────────────────────────────
    const table = new dynamodb.Table(this, 'SarathiTable', {
      tableName: 'sarathi',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'gsi1pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi1sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    table.addGlobalSecondaryIndex({
      indexName: 'GSI2',
      partitionKey: { name: 'gsi2pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi2sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    table.addGlobalSecondaryIndex({
      indexName: 'GSI3',
      partitionKey: { name: 'gsi3pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi3sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    table.addGlobalSecondaryIndex({
      indexName: 'GSI4',
      partitionKey: { name: 'gsi4pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi4sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ─── S3: paper texts + static assets ─────────────────────────────
    const bucket = new s3.Bucket(this, 'SarathiBucket', {
      bucketName: `sarathi-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });

    // ─── Cognito ─────────────────────────────────────────────────────
    const userPool = new cognito.UserPool(this, 'SarathiUserPool', {
      userPoolName: 'sarathi-users',
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const userPoolClient = userPool.addClient('SarathiAppClient', {
      authFlows: { userPassword: true, userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        callbackUrls: ['http://localhost:3000/callback'],
      },
    });

    userPool.addDomain('SarathiDomain', {
      cognitoDomain: { domainPrefix: 'sarathi-auth' },
    });

    // ─── Lambda: shared role + env ───────────────────────────────────
    const lambdaRole = new iam.Role(this, 'SarathiLambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });
    table.grantReadWriteData(lambdaRole);
    bucket.grantReadWrite(lambdaRole);

    const lambdaEnv = {
      TABLE_NAME: table.tableName,
      BUCKET_NAME: bucket.bucketName,
    };

    const lambdaCode = lambda.Code.fromAsset(REPO_ROOT, {
      exclude: ASSET_EXCLUDES,
      bundling: {
        image: lambda.Runtime.PYTHON_3_9.bundlingImage,
        command: [
          'bash', '-c',
          'pip install -r requirements.txt -t /asset-output && cp -r backend /asset-output/',
        ],
      },
    });

    // ─── Lambda: pipeline steps ──────────────────────────────────────
    const discoverFn = new lambda.Function(this, 'DiscoverFn', {
      functionName: 'sarathi-discover',
      runtime: lambda.Runtime.PYTHON_3_9,
      handler: 'backend.pipeline.discover.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
    });

    const triageFn = new lambda.Function(this, 'TriageFn', {
      functionName: 'sarathi-triage',
      runtime: lambda.Runtime.PYTHON_3_9,
      handler: 'backend.pipeline.triage.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 512,
    });

    const selectFn = new lambda.Function(this, 'SelectFn', {
      functionName: 'sarathi-select',
      runtime: lambda.Runtime.PYTHON_3_9,
      handler: 'backend.pipeline.select.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
    });

    const lensFn = new lambda.Function(this, 'LensFn', {
      functionName: 'sarathi-lens',
      runtime: lambda.Runtime.PYTHON_3_9,
      handler: 'backend.pipeline.lens.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
    });

    // ─── Lambda: API handler ─────────────────────────────────────────
    const feedFn = new lambda.Function(this, 'FeedApiFn', {
      functionName: 'sarathi-api-feed',
      runtime: lambda.Runtime.PYTHON_3_9,
      handler: 'backend.api.feed.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    // ─── Fargate: Digest step ────────────────────────────────────────
    const vpc = new ec2.Vpc(this, 'SarathiVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC },
      ],
    });

    const cluster = new ecs.Cluster(this, 'SarathiCluster', {
      vpc,
      clusterName: 'sarathi',
    });

    const digestTaskDef = new ecs.FargateTaskDefinition(this, 'DigestTaskDef', {
      cpu: 1024,
      memoryLimitMiB: 2048,
    });
    table.grantReadWriteData(digestTaskDef.taskRole);
    bucket.grantReadWrite(digestTaskDef.taskRole);

    digestTaskDef.addContainer('DigestContainer', {
      image: ecs.ContainerImage.fromAsset(REPO_ROOT, {
        file: 'Dockerfile.digest',
      }),
      environment: lambdaEnv,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'digest',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    // ─── Step Functions: pipeline orchestration ───────────────────────
    const discoverTask = new sfnTasks.LambdaInvoke(this, 'DiscoverStep', {
      lambdaFunction: discoverFn,
      resultPath: '$.discoverResult',
    });

    const triageTask = new sfnTasks.LambdaInvoke(this, 'TriageStep', {
      lambdaFunction: triageFn,
      resultPath: '$.triageResult',
    });

    const selectTask = new sfnTasks.LambdaInvoke(this, 'SelectStep', {
      lambdaFunction: selectFn,
      resultPath: '$.selectResult',
    });

    const digestTask = new sfnTasks.EcsRunTask(this, 'DigestStep', {
      integrationPattern: sfn.IntegrationPattern.RUN_JOB,
      cluster,
      taskDefinition: digestTaskDef,
      launchTarget: new sfnTasks.EcsFargateLaunchTarget({
        platformVersion: ecs.FargatePlatformVersion.LATEST,
      }),
      assignPublicIp: true,
      subnets: { subnetType: ec2.SubnetType.PUBLIC },
      resultPath: '$.digestResult',
    });

    const lensTask = new sfnTasks.LambdaInvoke(this, 'LensStep', {
      lambdaFunction: lensFn,
      resultPath: '$.lensResult',
    });

    const pipelineChain = discoverTask
      .next(triageTask)
      .next(selectTask)
      .next(digestTask)
      .next(lensTask);

    const stateMachine = new sfn.StateMachine(this, 'SarathiPipeline', {
      stateMachineName: 'sarathi-nightly-pipeline',
      definitionBody: sfn.DefinitionBody.fromChainable(pipelineChain),
      timeout: cdk.Duration.hours(2),
    });

    // ─── EventBridge: nightly trigger (2am UTC) ──────────────────────
    new events.Rule(this, 'NightlyTrigger', {
      schedule: events.Schedule.cron({ hour: '2', minute: '0' }),
      targets: [new targets.SfnStateMachine(stateMachine)],
    });

    // ─── API Gateway ─────────────────────────────────────────────────
    const authorizer = new apigw.CognitoUserPoolsAuthorizer(this, 'SarathiAuthorizer', {
      cognitoUserPools: [userPool],
    });

    const api = new apigw.RestApi(this, 'SarathiApi', {
      restApiName: 'sarathi-api',
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: apigw.Cors.ALL_METHODS,
      },
    });

    const feedResource = api.root.addResource('feed');
    feedResource.addMethod('GET', new apigw.LambdaIntegration(feedFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const feedCardResource = feedResource.addResource('{card_id}');
    feedCardResource.addMethod('GET', new apigw.LambdaIntegration(feedFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    // ─── Outputs ─────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TableName', { value: table.tableName });
    new cdk.CfnOutput(this, 'BucketName', { value: bucket.bucketName });
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
    new cdk.CfnOutput(this, 'StateMachineArn', { value: stateMachine.stateMachineArn });
  }
}

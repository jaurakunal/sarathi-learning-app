import * as path from 'path';
import * as cdk from 'aws-cdk-lib/core';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as sfnTasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as appsync from 'aws-cdk-lib/aws-appsync';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
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

    // ─── S3 Vectors: embeddings for RAG ──────────────────────────────
    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'SarathiVectorBucket', {
      vectorBucketName: `sarathi-vectors-${this.account}-${this.region}`,
    });

    const vectorIndex = new s3vectors.CfnIndex(this, 'PaperSectionsIndex', {
      vectorBucketName: `sarathi-vectors-${this.account}-${this.region}`,
      indexName: 'paper-sections',
      dimension: 1024,
      distanceMetric: 'cosine',
      dataType: 'float32',
    });
    vectorIndex.addDependency(vectorBucket);

    // ─── Cognito ─────────────────────────────────────────────────────
    const preSignUpFn = new lambda.Function(this, 'PreSignUpFn', {
      functionName: 'sarathi-pre-signup',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.auth.pre_signup.handler',
      code: lambda.Code.fromInline(`
def handler(event, context):
    event['response']['autoConfirmUser'] = True
    event['response']['autoVerifyEmail'] = True
    return event
`),
      timeout: cdk.Duration.seconds(5),
      memorySize: 128,
    });

    const userPool = new cognito.UserPool(this, 'SarathiUserPool', {
      userPoolName: 'sarathi-users',
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      lambdaTriggers: { preSignUp: preSignUpFn },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const userPoolClient = userPool.addClient('SarathiAppClient', {
      authFlows: { userPassword: true, userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        callbackUrls: [
          'http://localhost:3000/callback',
          'https://d0000000000000.cloudfront.net/callback',
        ],
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
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: ['*'],
    }));
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/sarathi/*`],
    }));
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3vectors:*'],
      resources: [
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/sarathi-vectors-${this.account}-${this.region}`,
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/sarathi-vectors-${this.account}-${this.region}/*`,
      ],
    }));
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['states:StartExecution'],
      resources: [`arn:aws:states:${this.region}:${this.account}:stateMachine:sarathi-nightly-pipeline`],
    }));
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['cognito-idp:AdminDeleteUser'],
      resources: [userPool.userPoolArn],
    }));

    // SSM Parameter for Semantic Scholar API key
    const s2ApiKeyParam = new ssm.StringParameter(this, 'S2ApiKeyParam', {
      parameterName: '/sarathi/semantic-scholar-api-key',
      stringValue: 'CHANGE_ME',
      description: 'Semantic Scholar API key (free tier, apply at semanticscholar.org/product/api)',
    });

    // SSM Parameter for VAPID keys (Web Push) — created manually, referenced here
    const vapidKeysParam = ssm.StringParameter.fromStringParameterName(
      this, 'VapidKeysParam', '/sarathi/vapid-keys',
    );

    const lambdaEnv = {
      TABLE_NAME: table.tableName,
      BUCKET_NAME: bucket.bucketName,
      S2_API_KEY_PARAM: s2ApiKeyParam.parameterName,
      VAPID_KEYS_PARAM: vapidKeysParam.parameterName,
      VECTOR_BUCKET_NAME: `sarathi-vectors-${this.account}-${this.region}`,
      VECTOR_INDEX_NAME: 'paper-sections',
      USER_POOL_ID: userPool.userPoolId,
    };

    const lambdaCode = lambda.Code.fromAsset(REPO_ROOT, {
      exclude: ASSET_EXCLUDES,
      bundling: {
        image: lambda.Runtime.PYTHON_3_12.bundlingImage,
        command: [
          'bash', '-c',
          'pip install --no-cache-dir -r requirements.txt -t /asset-output && cp -r backend /asset-output/',
        ],
      },
      assetHashType: cdk.AssetHashType.SOURCE,
    });

    // ─── Lambda: pipeline steps ──────────────────────────────────────
    const discoverFn = new lambda.Function(this, 'DiscoverFn', {
      functionName: 'sarathi-discover',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.discover.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 512,
    });

    const triageFn = new lambda.Function(this, 'TriageFn', {
      functionName: 'sarathi-triage',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.triage.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 512,
    });

    const selectFn = new lambda.Function(this, 'SelectFn', {
      functionName: 'sarathi-select',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.select.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
    });

    const lensFn = new lambda.Function(this, 'LensFn', {
      functionName: 'sarathi-lens',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.lens.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
    });

    const learnFn = new lambda.Function(this, 'LearnFn', {
      functionName: 'sarathi-learn',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.learn.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 512,
    });

    // ─── Lambda: API handlers ────────────────────────────────────────
    const feedFn = new lambda.Function(this, 'FeedApiFn', {
      functionName: 'sarathi-api-feed',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.feed.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const engagementFn = new lambda.Function(this, 'EngagementApiFn', {
      functionName: 'sarathi-api-engagement',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.engagement.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
    });

    const profileFn = new lambda.Function(this, 'ProfileApiFn', {
      functionName: 'sarathi-api-profile',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.profile.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const libraryFn = new lambda.Function(this, 'LibraryApiFn', {
      functionName: 'sarathi-api-library',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.library.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const convFn = new lambda.Function(this, 'ConvFn', {
      functionName: 'sarathi-api-conversations',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.conversations.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
    });

    const settingsFn = new lambda.Function(this, 'SettingsFn', {
      functionName: 'sarathi-api-settings',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.settings.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const onboardingFn = new lambda.Function(this, 'OnboardingFn', {
      functionName: 'sarathi-api-onboarding',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.onboarding.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
    });

    // onboardingConfirmFn needs STATE_MACHINE_ARN — added after stateMachine is created
    const onboardingConfirmFn = new lambda.Function(this, 'OnboardingConfirmFn', {
      functionName: 'sarathi-api-onboarding-confirm',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.onboarding_confirm.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const suggestFn = new lambda.Function(this, 'SuggestFn', {
      functionName: 'sarathi-api-suggest',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.suggest.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
    });

    const researchFn = new lambda.Function(this, 'ResearchFn', {
      functionName: 'sarathi-api-research',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.research.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
    });

    const pushFn = new lambda.Function(this, 'PushFn', {
      functionName: 'sarathi-api-push',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.api.push.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
    });

    const chatFn = new lambda.Function(this, 'ChatFn', {
      functionName: 'sarathi-chat',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.streaming.chat.handler',
      code: lambdaCode,
      environment: lambdaEnv,
      role: lambdaRole,
      timeout: cdk.Duration.seconds(29),
      memorySize: 512,
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
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    table.grantReadWriteData(digestTaskDef.taskRole);
    bucket.grantReadWrite(digestTaskDef.taskRole);
    digestTaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['*'],
    }));
    digestTaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/sarathi/*`],
    }));
    digestTaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['s3vectors:*'],
      resources: [
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/sarathi-vectors-${this.account}-${this.region}`,
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/sarathi-vectors-${this.account}-${this.region}/*`,
      ],
    }));

    digestTaskDef.addContainer('DigestContainer', {
      image: ecs.ContainerImage.fromAsset(REPO_ROOT, {
        file: 'Dockerfile.digest',
        platform: ecr_assets.Platform.LINUX_ARM64,
      }),
      environment: lambdaEnv,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'digest',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    // ─── Step Functions: pipeline orchestration ───────────────────────
    // Pipeline input comes from the fan-out Lambda (or manual trigger) with user_id
    const injectDefaults = new sfn.Pass(this, 'InjectDefaults', {
      resultPath: '$',
    });

    const pipelinePayload = {
      'user_id.$': '$.user_id',
      'table_name.$': '$.table_name',
      's3_bucket.$': '$.s3_bucket',
      'since_days.$': '$.since_days',
    };

    const discoverTask = new sfnTasks.LambdaInvoke(this, 'DiscoverStep', {
      lambdaFunction: discoverFn,
      payload: sfn.TaskInput.fromObject(pipelinePayload),
      resultPath: '$.discoverResult',
    });

    const triageTask = new sfnTasks.LambdaInvoke(this, 'TriageStep', {
      lambdaFunction: triageFn,
      payload: sfn.TaskInput.fromObject(pipelinePayload),
      resultPath: '$.triageResult',
    });

    const selectTask = new sfnTasks.LambdaInvoke(this, 'SelectStep', {
      lambdaFunction: selectFn,
      payload: sfn.TaskInput.fromObject(pipelinePayload),
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
      containerOverrides: [{
        containerDefinition: digestTaskDef.defaultContainer!,
        environment: [
          { name: 'USER_ID', value: sfn.JsonPath.stringAt('$.user_id') },
          { name: 'TABLE_NAME', value: sfn.JsonPath.stringAt('$.table_name') },
          { name: 'S3_BUCKET', value: sfn.JsonPath.stringAt('$.s3_bucket') },
        ],
      }],
      resultPath: '$.digestResult',
    });

    const lensTask = new sfnTasks.LambdaInvoke(this, 'LensStep', {
      lambdaFunction: lensFn,
      payload: sfn.TaskInput.fromObject(pipelinePayload),
      resultPath: '$.lensResult',
    });

    const learnTask = new sfnTasks.LambdaInvoke(this, 'LearnStep', {
      lambdaFunction: learnFn,
      payload: sfn.TaskInput.fromObject(pipelinePayload),
      resultPath: '$.learnResult',
    });

    const pipelineChain = injectDefaults
      .next(discoverTask)
      .next(triageTask)
      .next(selectTask)
      .next(digestTask)
      .next(lensTask)
      .next(learnTask);

    const stateMachine = new sfn.StateMachine(this, 'SarathiPipeline', {
      stateMachineName: 'sarathi-nightly-pipeline',
      definitionBody: sfn.DefinitionBody.fromChainable(pipelineChain),
      timeout: cdk.Duration.hours(2),
    });

    // Grant confirm Lambda access to start the pipeline for new users
    onboardingConfirmFn.addEnvironment('STATE_MACHINE_ARN', stateMachine.stateMachineArn);

    // ─── Fan-out Lambda + EventBridge: nightly per-user trigger ──────
    const fanoutFn = new lambda.Function(this, 'FanoutFn', {
      functionName: 'sarathi-pipeline-fanout',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.pipeline.fanout.handler',
      code: lambdaCode,
      environment: {
        TABLE_NAME: table.tableName,
        BUCKET_NAME: bucket.bucketName,
        STATE_MACHINE_ARN: stateMachine.stateMachineArn,
      },
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
    });
    table.grantReadData(fanoutFn);
    stateMachine.grantStartExecution(fanoutFn);

    new events.Rule(this, 'NightlyTrigger', {
      schedule: events.Schedule.cron({ hour: '2', minute: '0' }),
      targets: [new targets.LambdaFunction(fanoutFn)],
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

    api.addGatewayResponse('Default4xx', {
      type: apigw.ResponseType.DEFAULT_4XX,
      responseHeaders: {
        'Access-Control-Allow-Origin': "'*'",
        'Access-Control-Allow-Headers': "'Content-Type,Authorization'",
      },
    });

    api.addGatewayResponse('Default5xx', {
      type: apigw.ResponseType.DEFAULT_5XX,
      responseHeaders: {
        'Access-Control-Allow-Origin': "'*'",
        'Access-Control-Allow-Headers': "'Content-Type,Authorization'",
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

    const engagementResource = api.root.addResource('engagement');
    engagementResource.addMethod('POST', new apigw.LambdaIntegration(engagementFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const profileResource = api.root.addResource('profile');
    profileResource.addMethod('GET', new apigw.LambdaIntegration(profileFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const libraryResource = api.root.addResource('library');
    libraryResource.addMethod('GET', new apigw.LambdaIntegration(libraryFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const convResource = api.root.addResource('conversations');
    convResource.addMethod('GET', new apigw.LambdaIntegration(convFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    convResource.addMethod('POST', new apigw.LambdaIntegration(convFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    const convIdResource = convResource.addResource('{conv_id}');
    convIdResource.addMethod('PUT', new apigw.LambdaIntegration(convFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    convIdResource.addMethod('DELETE', new apigw.LambdaIntegration(convFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const settingsResource = api.root.addResource('settings');
    settingsResource.addMethod('GET', new apigw.LambdaIntegration(settingsFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    settingsResource.addMethod('PUT', new apigw.LambdaIntegration(settingsFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const accountResource = api.root.addResource('account');
    accountResource.addMethod('DELETE', new apigw.LambdaIntegration(settingsFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const onboardingResource = api.root.addResource('onboarding');
    onboardingResource.addMethod('GET', new apigw.LambdaIntegration(onboardingFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    onboardingResource.addMethod('POST', new apigw.LambdaIntegration(onboardingFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    const onboardingProfileResource = onboardingResource.addResource('profile');
    onboardingProfileResource.addMethod('PUT', new apigw.LambdaIntegration(onboardingConfirmFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const suggestResource = api.root.addResource('suggestions');
    suggestResource.addMethod('POST', new apigw.LambdaIntegration(suggestFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const researchResource = api.root.addResource('research');
    researchResource.addMethod('GET', new apigw.LambdaIntegration(researchFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const pushResource = api.root.addResource('push');
    const pushSubscriptionsResource = pushResource.addResource('subscriptions');
    pushSubscriptionsResource.addMethod('POST', new apigw.LambdaIntegration(pushFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });
    pushSubscriptionsResource.addMethod('DELETE', new apigw.LambdaIntegration(pushFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const chatResource = api.root.addResource('chat');
    chatResource.addMethod('POST', new apigw.LambdaIntegration(chatFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    const chatPaperResource = chatResource.addResource('{paper_id}');
    chatPaperResource.addMethod('GET', new apigw.LambdaIntegration(chatFn), {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
    });

    // ─── AppSync: real-time streaming chat ─────────────────────────
    const chatApi = new appsync.GraphqlApi(this, 'SarathiChatApi', {
      name: 'sarathi-chat',
      definition: appsync.Definition.fromFile(
        path.resolve(__dirname, 'schema.graphql'),
      ),
      authorizationConfig: {
        defaultAuthorization: {
          authorizationType: appsync.AuthorizationType.USER_POOL,
          userPoolConfig: { userPool },
        },
        additionalAuthorizationModes: [
          { authorizationType: appsync.AuthorizationType.IAM },
        ],
      },
    });

    // Dispatch Lambda — AppSync resolver, returns immediately
    const chatDispatchFn = new lambda.Function(this, 'ChatDispatchFn', {
      functionName: 'sarathi-chat-dispatch',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.streaming.chat_dispatch.handler',
      code: lambdaCode,
      environment: {
        ...lambdaEnv,
        STREAM_FUNCTION_NAME: 'sarathi-chat-stream',
      },
      role: lambdaRole,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
    });

    // Stream Lambda — invoked async, runs up to 5 min
    const chatStreamFn = new lambda.Function(this, 'ChatStreamFn', {
      functionName: 'sarathi-chat-stream',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'backend.streaming.chat_stream.handler',
      code: lambdaCode,
      environment: {
        ...lambdaEnv,
        APPSYNC_ENDPOINT: chatApi.graphqlUrl,
      },
      role: lambdaRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
    });

    // Grant the shared Lambda role permission to invoke the stream function
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [`arn:aws:lambda:${this.region}:${this.account}:function:sarathi-chat-stream`],
    }));

    // Grant the streaming Lambda permission to call AppSync mutations (publish chunks)
    chatApi.grant(chatStreamFn, appsync.IamResource.all(), 'appsync:GraphQL');

    const chatLambdaDs = chatApi.addLambdaDataSource('ChatLambdaDs', chatDispatchFn);
    chatLambdaDs.createResolver('SendMessageResolver', {
      typeName: 'Mutation',
      fieldName: 'sendMessage',
    });

    // NONE data source for publishChunk (called by Lambda via IAM, passes through to subscriptions)
    const noneDs = chatApi.addNoneDataSource('NoneDs');
    noneDs.createResolver('PublishChunkResolver', {
      typeName: 'Mutation',
      fieldName: 'publishChunk',
      requestMappingTemplate: appsync.MappingTemplate.fromString(`{
        "version": "2017-02-28",
        "payload": $util.toJson($context.arguments)
      }`),
      responseMappingTemplate: appsync.MappingTemplate.fromString('$util.toJson($context.result)'),
    });

    // ─── Frontend: S3 + CloudFront ─────────────────────────────────
    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `sarathi-frontend-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });

    const distribution = new cloudfront.Distribution(this, 'SarathiDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.seconds(0),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.seconds(0),
        },
      ],
    });

    new s3deploy.BucketDeployment(this, 'DeployFrontend', {
      sources: [s3deploy.Source.asset(path.resolve(REPO_ROOT, 'frontend', 'dist'))],
      destinationBucket: frontendBucket,
      distribution,
      distributionPaths: ['/*'],
    });

    // ─── Outputs ─────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TableName', { value: table.tableName });
    new cdk.CfnOutput(this, 'BucketName', { value: bucket.bucketName });
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
    new cdk.CfnOutput(this, 'StateMachineArn', { value: stateMachine.stateMachineArn });
    new cdk.CfnOutput(this, 'AppSyncUrl', { value: chatApi.graphqlUrl });
    new cdk.CfnOutput(this, 'DistributionUrl', { value: `https://${distribution.distributionDomainName}` });
  }
}

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

    const lambdaEnv = {
      TABLE_NAME: table.tableName,
      BUCKET_NAME: bucket.bucketName,
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
      timeout: cdk.Duration.minutes(5),
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
    const pipelineInput = {
      user_id: '00000000-0000-0000-0000-000000000000',
      table_name: table.tableName,
      s3_bucket: bucket.bucketName,
      since_days: 30,
    };

    const injectDefaults = new sfn.Pass(this, 'InjectDefaults', {
      result: sfn.Result.fromObject(pipelineInput),
      resultPath: '$',
    });

    const discoverTask = new sfnTasks.LambdaInvoke(this, 'DiscoverStep', {
      lambdaFunction: discoverFn,
      payload: sfn.TaskInput.fromObject(pipelineInput),
      resultPath: '$.discoverResult',
    });

    const triageTask = new sfnTasks.LambdaInvoke(this, 'TriageStep', {
      lambdaFunction: triageFn,
      payload: sfn.TaskInput.fromObject(pipelineInput),
      resultPath: '$.triageResult',
    });

    const selectTask = new sfnTasks.LambdaInvoke(this, 'SelectStep', {
      lambdaFunction: selectFn,
      payload: sfn.TaskInput.fromObject(pipelineInput),
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
          { name: 'USER_ID', value: pipelineInput.user_id },
          { name: 'TABLE_NAME', value: pipelineInput.table_name },
          { name: 'S3_BUCKET', value: pipelineInput.s3_bucket },
        ],
      }],
      resultPath: '$.digestResult',
    });

    const lensTask = new sfnTasks.LambdaInvoke(this, 'LensStep', {
      lambdaFunction: lensFn,
      payload: sfn.TaskInput.fromObject(pipelineInput),
      resultPath: '$.lensResult',
    });

    const learnTask = new sfnTasks.LambdaInvoke(this, 'LearnStep', {
      lambdaFunction: learnFn,
      payload: sfn.TaskInput.fromObject(pipelineInput),
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

#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { SarathiStack } from '../lib/sarathi-stack';

const app = new cdk.App();
new SarathiStack(app, 'SarathiStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
  },
});

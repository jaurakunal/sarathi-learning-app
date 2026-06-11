#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { SarathiStack } from '../lib/sarathi-stack';

const app = new cdk.App();
new SarathiStack(app, 'SarathiStack', {
  env: { account: '123456789012', region: 'us-east-1' },
});

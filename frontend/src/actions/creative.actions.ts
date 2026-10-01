'use server';

import {
  creativeService,
  GenerateCreativeRequest,
  CreativeJobResponse,
} from '../services/creative.service';

export async function generateCreativeAction(
  data: GenerateCreativeRequest
): Promise<CreativeJobResponse> {
  return creativeService.generateCreative(data);
}

export async function pollJobStatusAction(
  jobId: string
): Promise<CreativeJobResponse> {
  return creativeService.pollJobStatus(jobId);
}

"""
This module contains all the logic to retrieve RNA-Seq data from GEO.
"""

import gzip
import logging
from subprocess import Popen
import os
from os.path import join
from urllib.parse import urlparse, parse_qs

from bioluigi.tasks.utils import DynamicTaskWithOutputMixin, DynamicWrapperTask
import luigi
from luigi.util import requires
import requests

from ..config import rnaseq_pipeline
from ..miniml_utils import collect_geo_samples, collect_geo_samples_info
from .sra import DownloadSraExperiment

cfg = rnaseq_pipeline()

logger = logging.getLogger('luigi-interface')

class DownloadGeoSampleMetadata(luigi.Task):
    """
    Download the MiNiML metadata for a given GEO Sample.
    """
    gsm = luigi.Parameter()

    resources = {'geo_http_connections': 1}

    def run(self):
        res = requests.get('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi', params=dict(acc=self.gsm, form='xml'))
        res.raise_for_status()
        with self.output().open('w') as f:
            f.write(res.text)

    def output(self):
        return luigi.LocalTarget(join(cfg.OUTPUT_DIR, cfg.METADATA, 'geo', '{}.xml'.format(self.gsm)))

@requires(DownloadGeoSampleMetadata)
class DownloadGeoSample(DynamicTaskWithOutputMixin, DynamicWrapperTask):
    """
    Download a GEO Sample given a runinfo file and
    """

    @property
    def sample_id(self):
        return self.gsm

    def run(self):
        samples_info = collect_geo_samples_info(self.input().path)
        if not self.gsm in samples_info:
            raise RuntimeError('{} GEO record is not linked to SRA.'.format(self.gsm))
        platform, srx_url = samples_info[self.gsm]
        srx = parse_qs(urlparse(srx_url).query)['term'][0]
        yield DownloadSraExperiment(srx)

class DownloadGeoSeriesMetadata(luigi.Task):
    """
    Download a GEO Series metadata containg information about related GEO
    Samples.
    """
    gse = luigi.Parameter()

    resources = {'geo_http_connections': 1}

    def run(self):
        res = requests.get('https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi', params=dict(acc=self.gse, form='xml', targ='gsm'))
        res.raise_for_status()
        with self.output().open('w') as f:
            f.write(res.text)

    def output(self):
        # TODO: remove the _family suffix
        return luigi.LocalTarget(join(cfg.OUTPUT_DIR, cfg.METADATA, 'geo', '{}_family.xml'.format(self.gse)))

@requires(DownloadGeoSeriesMetadata)
class DownloadGeoSeries(DynamicTaskWithOutputMixin, DynamicWrapperTask):
    """
    Download all GEO Samples related to a GEO Series.
    """

    def run(self):
        gsms = collect_geo_samples(self.input().path)
        if not gsms:
            raise ValueError('{} has no related GEO samples with RNA-Seq data.'.format(self.gse))
        yield [DownloadGeoSample(gsm) for gsm in gsms]

@requires(DownloadGeoSeriesMetadata, DownloadGeoSeries)
class ExtractGeoSeriesBatchInfo(luigi.Task):
    """
    Extract the GEO Series batch information by looking up the GEO Series
    metadata and some downloaded FASTQs headers.
    """

    def run(self):
        geo_series_metadata, samples = self.requires()
        samples = next(samples.run())
        sample_geo_metadata = collect_geo_samples_info(geo_series_metadata.output().path)
        with self.output().open('w') as info_out:
            for sample in samples:
                if len(sample.output()) == 0:
                    logger.warning('GEO sample %s has no associated FASTQs from which batch information can be extracted.', sample.sample_id)
                    continue

                # TODO: find a cleaner way to obtain the SRA run accession
                for fastq in sample.output():
                    # strip the two extensions (.fastq.gz)
                    fastq_name, _ = os.path.splitext(fastq.path)
                    fastq_name, _ = os.path.splitext(fastq_name)

                    # is this necessary?
                    fastq_id = os.path.basename(fastq_name)

                    platform_id, srx_uri = sample_geo_metadata[sample.sample_id]

                    with gzip.open(fastq.path, 'rt') as f:
                        fastq_header = f.readline().rstrip()

                    info_out.write('\t'.join([sample.sample_id, fastq_id, platform_id, srx_uri, fastq_header]) + '\n')

    def output(self):
        # TODO: organize batch info per source
        return luigi.LocalTarget(join(cfg.OUTPUT_DIR, cfg.BATCHINFODIR, '{}.fastq-headers-table.txt'.format(self.gse)))

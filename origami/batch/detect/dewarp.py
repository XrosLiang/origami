#!/usr/bin/env python3

import click
import shapely.ops
import shapely.wkt
import zipfile
import logging

from pathlib import Path

from origami.batch.core.processor import Processor
from origami.batch.core.io import Artifact, Stage, Input, Output
from origami.core.dewarp import Grid, Samples


def dewarped_contours(warped, transformer, min_areas):
	with open(warped.path(Artifact.CONTOURS), "rb") as f:
		with zipfile.ZipFile(f, "r") as zf:
			for name in zf.namelist():
				if not name.endswith(".wkt"):
					continue
				path = tuple(name.rsplit(".", 1)[0].split("/"))
				geom = shapely.wkt.loads(zf.read(name).decode("utf8"))
				warped_geom = geom
				assert not warped_geom.is_empty
				geom = shapely.ops.transform(transformer, geom)
				if geom.is_empty or geom.area < min_areas.get(path[0], 0):
					logging.warning(
						"lost contour %s (A=%.1f) during dewarping." % (
							path, warped_geom.area))
					continue
				if geom.geom_type not in ("Polygon", "LineString"):
					logging.error("dewarped contour %s is %s" % (
						name, geom.geom_type))
				if not geom.is_valid:
					geom = geom.buffer(0)
					if not geom.is_valid:
						logging.error("invalid geom %s", geom)
				yield name, geom.wkt.encode("utf8")


class DewarpProcessor(Processor):
	def __init__(self, options):
		super().__init__(options)
		self._options = options

	@property
	def processor_name(self):
		return __loader__.name

	def artifacts(self):
		return [
			("warped", Input(
				Artifact.CONTOURS,
				Artifact.FLOW,
				stage=Stage.WARPED)),
			("output", Output(
				Artifact.DEWARPING_TRANSFORM,
				Artifact.CONTOURS,
				stage=Stage.DEWARPED))
		]

	def process(self, page_path: Path, warped, output):
		blocks = warped.regions.by_path

		if not blocks:
			return

		page = warped.page

		with warped.flow as zf:
			samples_h = Samples.open(zf, "h")
			samples_v = Samples.open(zf, "v")

		grid = Grid.create(
			page, samples_h, samples_v,
			grid_res=self._options["grid_cell_size"])

		min_areas = dict(
			regions=grid.geometry.rel_area(
				self._options["region_area"]),
			separators=0)

		with output.contours(copy_meta_from=warped) as zf:
			for name, data in dewarped_contours(
				warped, grid.transformer, min_areas=min_areas):
				zf.writestr(name, data)

		with output.dewarping_transform() as f:
			grid.save(f)


@click.command()
@click.argument(
	'data_path',
	type=click.Path(exists=True),
	required=True)
@click.option(
	'--grid-cell-size',
	type=int,
	default=25,
	help="grid cell size used for dewarping (smaller is better, but takes longer).")
@click.option(
	'--region-area',
	type=float,
	default=0,
	help="Ignore regions below this relative size.")
@Processor.options
def dewarp(data_path, **kwargs):
	""" Dewarp documents in DATA_PATH. """
	processor = DewarpProcessor(kwargs)
	processor.traverse(data_path)


if __name__ == "__main__":
	dewarp()


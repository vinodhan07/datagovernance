"""
lineage_tracker.py
══════════════════
Production-grade Pandas lineage tracking engine.

Wraps Pandas operations to automatically capture:
  • Dataset-level lineage  (source → target)
  • Column-level lineage   (source.col → [transforms] → target.col)
  • Transformation DAG     (nodes + edges for visualization)

Usage:
    tracker = LineageTracker(job_name="MariaDB ETL")
    df = tracker.read_sql("SELECT * FROM orders", engine, source_uri="mysql://…/orders")
    df = tracker.drop_duplicates(df, subset=["order_id"])
    df["email"] = tracker.apply_column(df, "email", clean_email, "clean_email")
    df["amount"] = tracker.to_numeric(df, "amount")
    df["amount"] = tracker.abs_column(df, "amount")
    tracker.to_sql(df, "orders", engine, target_uri="postgresql://…/orders")
    result = tracker.finalize()
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pandas as pd

logger = logging.getLogger("dataguard.lineage")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data structures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class ColumnLineageRecord:
    """Tracks a single column's journey from source to target."""
    source_dataset: str
    source_column: str
    target_dataset: str
    target_column: str
    transformations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dataset": self.source_dataset,
            "source_column": self.source_column,
            "target_dataset": self.target_dataset,
            "target_column": self.target_column,
            "transformations": list(self.transformations),
        }


@dataclass
class DatasetLineageRecord:
    """Tracks a source-to-target dataset relationship."""
    source_dataset: str
    source_uri: str
    target_dataset: str
    target_uri: str
    transformation: str
    column_lineage: list[ColumnLineageRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dataset": self.source_dataset,
            "source_uri": self.source_uri,
            "target_dataset": self.target_dataset,
            "target_uri": self.target_uri,
            "transformation": self.transformation,
            "column_lineage": [c.to_dict() for c in self.column_lineage],
        }


@dataclass
class TransformationStep:
    """A single transformation applied to one or more columns."""
    id: str
    operation: str          # e.g. "drop_duplicates", "apply", "to_numeric"
    function_name: str      # e.g. "clean_email", "abs", "pd.to_numeric"
    columns_affected: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)
    order_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "function_name": self.function_name,
            "columns_affected": list(self.columns_affected),
            "parameters": dict(self.parameters),
            "order_index": self.order_index,
        }


@dataclass
class DAGNode:
    """A node in the transformation DAG."""
    id: str
    node_type: str          # "dataset" | "operation"
    label: str
    columns: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "type": self.node_type,
            "data": {
                "label": self.label,
            },
            "position": self.metadata.get("position", {"x": 0, "y": 0}),
        }
        if self.columns:
            result["data"]["columns"] = list(self.columns)
        if "operation" in self.metadata:
            result["data"]["operation"] = self.metadata["operation"]
        return result


@dataclass
class DAGEdge:
    """An edge in the transformation DAG."""
    id: str
    source: str
    target: str
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
        }
        if self.columns:
            result["data"] = {"columns": list(self.columns)}
        return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Internal tracking state per DataFrame
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class _TrackedDataFrame:
    """Internal state attached to a tracked DataFrame."""
    df_id: str
    source_dataset: str
    source_uri: str
    original_columns: list[str]
    current_columns: list[str]
    # Per-column: list of transformations applied so far
    column_transforms: dict[str, list[str]] = field(default_factory=dict)
    # Per-column: the original source column name (handles renames)
    column_origins: dict[str, str] = field(default_factory=dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main tracker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LineageTracker:
    """
    Tracks data lineage through Pandas operations.

    Create one instance per pipeline run. Call its wrapper methods instead
    of raw Pandas calls. When the pipeline completes, call ``finalize()``
    to get the full lineage metadata.
    """

    def __init__(self, job_name: str, integration_id: str = "") -> None:
        self.job_id: str = str(uuid.uuid4())
        self.job_name: str = job_name
        self.integration_id: str = integration_id
        self.started_at: datetime = datetime.now(timezone.utc)

        # DataFrame registry: df id() -> _TrackedDataFrame
        self._dataframes: dict[int, _TrackedDataFrame] = {}

        # Ordered list of all transformation steps
        self._transformations: list[TransformationStep] = []
        self._step_counter: int = 0

        # DAG elements
        self._dag_nodes: list[DAGNode] = []
        self._dag_edges: list[DAGEdge] = []
        self._edge_counter: int = 0

        # Dataset lineage (populated on to_sql/finalize)
        self._dataset_lineage: list[DatasetLineageRecord] = []

        # Column lineage (populated on to_sql/finalize)
        self._column_lineage: list[ColumnLineageRecord] = []

        logger.info("LineageTracker initialized: job=%s id=%s", job_name, self.job_id)

    # ─── DataFrame registration ───────────────────────────────────────────────

    def _register_df(
        self,
        df: pd.DataFrame,
        source_dataset: str,
        source_uri: str,
    ) -> _TrackedDataFrame:
        """Register a DataFrame for lineage tracking."""
        cols = df.columns.tolist()
        tracked = _TrackedDataFrame(
            df_id=str(uuid.uuid4()),
            source_dataset=source_dataset,
            source_uri=source_uri,
            original_columns=list(cols),
            current_columns=list(cols),
            column_transforms={col: [] for col in cols},
            column_origins={col: col for col in cols},
        )
        self._dataframes[id(df)] = tracked

        # Add source node to DAG
        node_id = f"src:{source_uri}"
        if not any(n.id == node_id for n in self._dag_nodes):
            self._dag_nodes.append(DAGNode(
                id=node_id,
                node_type="dataset",
                label=f"{source_dataset} (Source)",
                columns=list(cols),
                metadata={"uri": source_uri},
            ))

        logger.info(
            "Registered DataFrame: dataset=%s columns=%d uri=%s",
            source_dataset, len(cols), source_uri,
        )
        return tracked

    def _get_tracked(self, df: pd.DataFrame) -> _TrackedDataFrame | None:
        """Look up tracking state for a DataFrame."""
        return self._dataframes.get(id(df))

    def _reregister(self, old_df: pd.DataFrame, new_df: pd.DataFrame) -> None:
        """When Pandas returns a new DataFrame object, move tracking state."""
        tracked = self._dataframes.pop(id(old_df), None)
        if tracked:
            tracked.current_columns = new_df.columns.tolist()
            self._dataframes[id(new_df)] = tracked

    def _add_transform_step(
        self,
        operation: str,
        function_name: str,
        columns_affected: list[str],
        parameters: dict[str, Any] | None = None,
    ) -> TransformationStep:
        """Record a transformation step."""
        self._step_counter += 1
        step = TransformationStep(
            id=str(uuid.uuid4()),
            operation=operation,
            function_name=function_name,
            columns_affected=columns_affected,
            parameters=parameters or {},
            order_index=self._step_counter,
        )
        self._transformations.append(step)

        # Add operation node to DAG
        op_label = function_name
        if columns_affected:
            op_label = f"{function_name}({', '.join(columns_affected[:3])})"
            if len(columns_affected) > 3:
                op_label += f" +{len(columns_affected)-3} more"

        op_node_id = f"op:{self._step_counter}:{operation}"
        self._dag_nodes.append(DAGNode(
            id=op_node_id,
            node_type="operation",
            label=op_label,
            columns=columns_affected,
            metadata={"operation": operation, "function": function_name},
        ))

        # Connect to previous node
        if len(self._dag_nodes) >= 2:
            prev_node = self._dag_nodes[-2]
            self._edge_counter += 1
            self._dag_edges.append(DAGEdge(
                id=f"e{self._edge_counter}",
                source=prev_node.id,
                target=op_node_id,
                columns=columns_affected,
            ))

        logger.debug(
            "Transform step #%d: %s(%s) on columns %s",
            self._step_counter, operation, function_name, columns_affected,
        )
        return step

    # ─── Source operations ────────────────────────────────────────────────────

    def read_sql(
        self,
        query: str,
        con: Any,
        source_uri: str,
        source_dataset: str = "",
    ) -> pd.DataFrame:
        """Tracked wrapper for pd.read_sql()."""
        df = pd.read_sql(query, con=con)

        if not source_dataset:
            # Try to extract table name from query
            import re
            match = re.search(r"FROM\s+[`'\"]?(\w+)[`'\"]?", query, re.IGNORECASE)
            source_dataset = match.group(1) if match else "unknown_table"

        self._register_df(df, source_dataset, source_uri)

        self._add_transform_step(
            operation="read_sql",
            function_name="pd.read_sql",
            columns_affected=df.columns.tolist(),
            parameters={"query": query[:200], "source_uri": source_uri},
        )

        logger.info("read_sql: %d rows, %d columns from %s", len(df), len(df.columns), source_dataset)
        return df

    def read_csv(
        self,
        filepath: str,
        source_uri: str = "",
        source_dataset: str = "",
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Tracked wrapper for pd.read_csv()."""
        df = pd.read_csv(filepath, **kwargs)

        if not source_dataset:
            import os
            source_dataset = os.path.basename(filepath)
        if not source_uri:
            source_uri = f"file://{filepath}"

        self._register_df(df, source_dataset, source_uri)

        self._add_transform_step(
            operation="read_csv",
            function_name="pd.read_csv",
            columns_affected=df.columns.tolist(),
            parameters={"filepath": filepath, "source_uri": source_uri},
        )

        logger.info("read_csv: %d rows, %d columns from %s", len(df), len(df.columns), source_dataset)
        return df

    # ─── Transformation operations ────────────────────────────────────────────

    def drop_duplicates(
        self,
        df: pd.DataFrame,
        subset: list[str] | None = None,
        keep: str = "first",
    ) -> pd.DataFrame:
        """Tracked wrapper for df.drop_duplicates()."""
        before_count = len(df)
        result = df.drop_duplicates(subset=subset, keep=keep)

        self._reregister(df, result)

        cols_affected = subset or df.columns.tolist()
        self._add_transform_step(
            operation="drop_duplicates",
            function_name="drop_duplicates",
            columns_affected=cols_affected,
            parameters={
                "subset": subset,
                "keep": keep,
                "rows_before": before_count,
                "rows_after": len(result),
                "rows_dropped": before_count - len(result),
            },
        )

        # drop_duplicates doesn't change column lineage, only row count
        tracked = self._get_tracked(result)
        if tracked:
            for col in cols_affected:
                if col in tracked.column_transforms:
                    tracked.column_transforms[col].append("drop_duplicates")

        logger.info(
            "drop_duplicates: %d → %d rows (dropped %d)",
            before_count, len(result), before_count - len(result),
        )
        return result

    def apply_column(
        self,
        df: pd.DataFrame,
        column: str,
        func: Callable[..., Any],
        transform_name: str = "",
    ) -> pd.Series:
        """
        Tracked wrapper for df[column].apply(func).

        Returns the transformed Series. Caller assigns it:
            df["email"] = tracker.apply_column(df, "email", clean_email, "clean_email")
        """
        if not transform_name:
            transform_name = getattr(func, "__name__", "apply")

        result = df[column].apply(func)

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append(transform_name)

        self._add_transform_step(
            operation="apply",
            function_name=transform_name,
            columns_affected=[column],
            parameters={"function": transform_name},
        )

        logger.info("apply: %s(%s)", transform_name, column)
        return result

    def to_numeric(
        self,
        df: pd.DataFrame,
        column: str,
        errors: str = "coerce",
    ) -> pd.Series:
        """
        Tracked wrapper for pd.to_numeric(df[column]).

        Returns the converted Series. Caller assigns it:
            df["amount"] = tracker.to_numeric(df, "amount")
        """
        result = pd.to_numeric(df[column], errors=errors)

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append("pd.to_numeric")

        self._add_transform_step(
            operation="to_numeric",
            function_name="pd.to_numeric",
            columns_affected=[column],
            parameters={"errors": errors},
        )

        logger.info("to_numeric: %s", column)
        return result

    def abs_column(
        self,
        df: pd.DataFrame,
        column: str,
    ) -> pd.Series:
        """
        Tracked wrapper for df[column].abs().

        Returns the absolute-valued Series. Caller assigns it:
            df["amount"] = tracker.abs_column(df, "amount")
        """
        result = df[column].abs()

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append("abs")

        self._add_transform_step(
            operation="abs",
            function_name="abs",
            columns_affected=[column],
            parameters={},
        )

        logger.info("abs: %s", column)
        return result

    def to_datetime(
        self,
        df: pd.DataFrame,
        columns: list[str],
        errors: str = "coerce",
    ) -> pd.DataFrame:
        """
        Tracked wrapper for pd.to_datetime on multiple columns.

        Modifies df in place and returns it.
        """
        for col in columns:
            if col in df.columns:
                df[col] = df[col].replace("(NULL)", pd.NA)
                df[col] = pd.to_datetime(df[col], errors=errors)

                tracked = self._get_tracked(df)
                if tracked and col in tracked.column_transforms:
                    tracked.column_transforms[col].append("replace_null")
                    tracked.column_transforms[col].append("pd.to_datetime")

        self._add_transform_step(
            operation="to_datetime",
            function_name="pd.to_datetime",
            columns_affected=columns,
            parameters={"errors": errors},
        )

        logger.info("to_datetime: %s", columns)
        return df

    def replace_values(
        self,
        df: pd.DataFrame,
        column: str,
        old_value: Any,
        new_value: Any,
    ) -> pd.Series:
        """Tracked wrapper for df[column].replace(old, new)."""
        result = df[column].replace(old_value, new_value)

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append(f"replace({old_value!r}→{new_value!r})")

        self._add_transform_step(
            operation="replace",
            function_name="replace",
            columns_affected=[column],
            parameters={"old_value": str(old_value), "new_value": str(new_value)},
        )

        logger.info("replace: %s (%s → %s)", column, old_value, new_value)
        return result

    def fillna(
        self,
        df: pd.DataFrame,
        column: str,
        value: Any,
    ) -> pd.Series:
        """Tracked wrapper for df[column].fillna(value)."""
        result = df[column].fillna(value)

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append(f"fillna({value!r})")

        self._add_transform_step(
            operation="fillna",
            function_name="fillna",
            columns_affected=[column],
            parameters={"value": str(value)},
        )

        logger.info("fillna: %s with %s", column, value)
        return result

    def astype_column(
        self,
        df: pd.DataFrame,
        column: str,
        dtype: Any,
    ) -> pd.Series:
        """Tracked wrapper for df[column].astype(dtype)."""
        result = df[column].astype(dtype)

        tracked = self._get_tracked(df)
        if tracked and column in tracked.column_transforms:
            tracked.column_transforms[column].append(f"astype({dtype})")

        self._add_transform_step(
            operation="astype",
            function_name="astype",
            columns_affected=[column],
            parameters={"dtype": str(dtype)},
        )

        logger.info("astype: %s → %s", column, dtype)
        return result

    def rename_columns(
        self,
        df: pd.DataFrame,
        columns_map: dict[str, str],
    ) -> pd.DataFrame:
        """Tracked wrapper for df.rename(columns=...)."""
        result = df.rename(columns=columns_map)
        self._reregister(df, result)

        tracked = self._get_tracked(result)
        if tracked:
            for old_name, new_name in columns_map.items():
                if old_name in tracked.column_transforms:
                    tracked.column_transforms[new_name] = tracked.column_transforms.pop(old_name)
                    tracked.column_transforms[new_name].append(f"rename({old_name}→{new_name})")
                if old_name in tracked.column_origins:
                    tracked.column_origins[new_name] = tracked.column_origins.pop(old_name)
            tracked.current_columns = result.columns.tolist()

        self._add_transform_step(
            operation="rename",
            function_name="rename",
            columns_affected=list(columns_map.keys()),
            parameters={"mapping": columns_map},
        )

        logger.info("rename: %s", columns_map)
        return result

    def drop_columns(
        self,
        df: pd.DataFrame,
        columns: list[str],
    ) -> pd.DataFrame:
        """Tracked wrapper for df.drop(columns=...)."""
        result = df.drop(columns=columns, errors="ignore")
        self._reregister(df, result)

        tracked = self._get_tracked(result)
        if tracked:
            for col in columns:
                tracked.column_transforms.pop(col, None)
                tracked.column_origins.pop(col, None)
            tracked.current_columns = result.columns.tolist()

        self._add_transform_step(
            operation="drop",
            function_name="drop",
            columns_affected=columns,
            parameters={"columns": columns},
        )

        logger.info("drop: %s", columns)
        return result

    def query_rows(
        self,
        df: pd.DataFrame,
        query_str: str,
    ) -> pd.DataFrame:
        """
        Tracked wrapper for df.query(query_str).

        Records which columns are referenced in the filter expression.
        Returns the filtered DataFrame.
        """
        result = df.query(query_str)
        self._reregister(df, result)

        # Extract referenced column names from the query string (best-effort)
        import re
        referenced = re.findall(r"\b([A-Za-z_]\w*)\b", query_str)
        cols_affected = [c for c in referenced if c in df.columns]
        if not cols_affected:
            cols_affected = df.columns.tolist()

        tracked = self._get_tracked(result)
        if tracked:
            for col in cols_affected:
                if col in tracked.column_transforms:
                    tracked.column_transforms[col].append(f"filter({query_str[:40]})")

        self._add_transform_step(
            operation="query",
            function_name="query",
            columns_affected=cols_affected,
            parameters={"query": query_str, "rows_before": len(df), "rows_after": len(result)},
        )

        logger.info("query: '%s' → %d → %d rows", query_str[:60], len(df), len(result))
        return result

    def concat_dataframes(
        self,
        dfs: list[pd.DataFrame],
        axis: int = 0,
        ignore_index: bool = True,
    ) -> pd.DataFrame:
        """
        Tracked wrapper for pd.concat().

        Merges lineage tracking from all source DataFrames into the result.
        Returns the concatenated DataFrame.
        """
        result = pd.concat(dfs, axis=axis, ignore_index=ignore_index)

        # Pick the first tracked source as the primary lineage carrier
        primary_tracked: "_TrackedDataFrame | None" = None
        for src_df in dfs:
            t = self._get_tracked(src_df)
            if t is not None:
                primary_tracked = t
                break

        source_name = primary_tracked.source_dataset if primary_tracked else "concat_source"
        source_uri = primary_tracked.source_uri if primary_tracked else "concat://internal"

        new_tracked = _TrackedDataFrame(
            df_id=str(uuid.uuid4()),
            source_dataset=source_name,
            source_uri=source_uri,
            original_columns=result.columns.tolist(),
            current_columns=result.columns.tolist(),
            column_transforms={col: ["concat"] for col in result.columns},
            column_origins={col: col for col in result.columns},
        )

        # Carry forward transforms from primary source
        if primary_tracked:
            for col, transforms in primary_tracked.column_transforms.items():
                if col in new_tracked.column_transforms:
                    new_tracked.column_transforms[col] = list(transforms) + ["concat"]
                if col in primary_tracked.column_origins:
                    new_tracked.column_origins[col] = primary_tracked.column_origins[col]

        self._dataframes[id(result)] = new_tracked

        self._add_transform_step(
            operation="concat",
            function_name="concat",
            columns_affected=result.columns.tolist(),
            parameters={"axis": axis, "num_frames": len(dfs), "row_count": len(result)},
        )

        logger.info("concat: %d DataFrames → %d rows × %d cols", len(dfs), len(result), len(result.columns))
        return result

    def merge_dataframes(
        self,
        left: pd.DataFrame,
        right: pd.DataFrame,
        on: str | list[str] | None = None,
        how: str = "inner",
        left_on: str | list[str] | None = None,
        right_on: str | list[str] | None = None,
    ) -> pd.DataFrame:
        """Tracked wrapper for pd.merge()."""
        result = pd.merge(left, right, on=on, how=how, left_on=left_on, right_on=right_on)

        # Merge tracking from both sides
        left_tracked = self._get_tracked(left)
        right_tracked = self._get_tracked(right)

        join_cols = on if isinstance(on, list) else ([on] if on else [])

        # Create new tracking for the merged result
        source_name = "merged"
        source_uri = "merge://internal"
        if left_tracked:
            source_name = left_tracked.source_dataset
            source_uri = left_tracked.source_uri

        new_tracked = _TrackedDataFrame(
            df_id=str(uuid.uuid4()),
            source_dataset=source_name,
            source_uri=source_uri,
            original_columns=result.columns.tolist(),
            current_columns=result.columns.tolist(),
            column_transforms={col: ["merge"] for col in result.columns},
            column_origins={col: col for col in result.columns},
        )

        # Carry forward transforms from left
        if left_tracked:
            for col, transforms in left_tracked.column_transforms.items():
                if col in new_tracked.column_transforms:
                    new_tracked.column_transforms[col] = list(transforms) + ["merge"]
                if col in left_tracked.column_origins:
                    new_tracked.column_origins[col] = left_tracked.column_origins[col]

        # Carry forward transforms from right
        if right_tracked:
            for col, transforms in right_tracked.column_transforms.items():
                if col in new_tracked.column_transforms:
                    existing = new_tracked.column_transforms.get(col, [])
                    if not existing or existing == ["merge"]:
                        new_tracked.column_transforms[col] = list(transforms) + ["merge"]

        self._dataframes[id(result)] = new_tracked

        self._add_transform_step(
            operation="merge",
            function_name="merge",
            columns_affected=result.columns.tolist(),
            parameters={"on": join_cols, "how": how},
        )

        logger.info("merge: %s join on %s → %d rows", how, join_cols, len(result))
        return result

    def groupby_agg(
        self,
        df: pd.DataFrame,
        group_cols: list[str],
        agg_dict: dict[str, str | list[str]],
    ) -> pd.DataFrame:
        """Tracked wrapper for df.groupby().agg()."""
        result = df.groupby(group_cols).agg(agg_dict).reset_index()

        self._reregister(df, result)

        all_cols = list(set(group_cols + list(agg_dict.keys())))

        tracked = self._get_tracked(result)
        if tracked:
            for col in result.columns:
                if col in group_cols:
                    tracked.column_transforms.setdefault(col, []).append("groupby_key")
                else:
                    tracked.column_transforms.setdefault(col, []).append(f"agg({agg_dict.get(col, 'unknown')})")

        self._add_transform_step(
            operation="groupby_agg",
            function_name="groupby.agg",
            columns_affected=all_cols,
            parameters={"group_cols": group_cols, "agg_dict": {k: str(v) for k, v in agg_dict.items()}},
        )

        logger.info("groupby_agg: group by %s, agg %s → %d rows", group_cols, list(agg_dict.keys()), len(result))
        return result

    # ─── Target operations ────────────────────────────────────────────────────

    def to_sql(
        self,
        df: pd.DataFrame,
        table_name: str,
        con: Any,
        target_uri: str,
        if_exists: str = "replace",
        index: bool = False,
    ) -> None:
        """
        Tracked wrapper for df.to_sql().

        This is the terminal operation that finalizes lineage for this
        DataFrame and builds the column lineage records.
        """
        # Write the data
        df.to_sql(table_name, con=con, if_exists=if_exists, index=index)

        # Build column lineage
        tracked = self._get_tracked(df)
        if tracked:
            # Dataset lineage
            ds_record = DatasetLineageRecord(
                source_dataset=tracked.source_dataset,
                source_uri=tracked.source_uri,
                target_dataset=table_name,
                target_uri=target_uri,
                transformation="ETL Pipeline",
            )

            # Column lineage for each surviving column
            for col in df.columns:
                transforms = tracked.column_transforms.get(col, [])
                source_col = tracked.column_origins.get(col, col)

                col_record = ColumnLineageRecord(
                    source_dataset=tracked.source_dataset,
                    source_column=source_col,
                    target_dataset=table_name,
                    target_column=col,
                    transformations=list(transforms),
                )
                ds_record.column_lineage.append(col_record)
                self._column_lineage.append(col_record)

            self._dataset_lineage.append(ds_record)

        # Add target node to DAG
        tgt_node_id = f"tgt:{target_uri}"
        if not any(n.id == tgt_node_id for n in self._dag_nodes):
            self._dag_nodes.append(DAGNode(
                id=tgt_node_id,
                node_type="dataset",
                label=f"{table_name} (Target)",
                columns=df.columns.tolist(),
                metadata={"uri": target_uri},
            ))

        # Connect last operation to target
        if len(self._dag_nodes) >= 2:
            prev_node = self._dag_nodes[-2]
            if prev_node.id != tgt_node_id:
                self._edge_counter += 1
                self._dag_edges.append(DAGEdge(
                    id=f"e{self._edge_counter}",
                    source=prev_node.id,
                    target=tgt_node_id,
                    columns=df.columns.tolist(),
                ))

        self._add_transform_step(
            operation="to_sql",
            function_name="to_sql",
            columns_affected=df.columns.tolist(),
            parameters={
                "table_name": table_name,
                "target_uri": target_uri,
                "if_exists": if_exists,
                "row_count": len(df),
            },
        )

        logger.info(
            "to_sql: wrote %d rows × %d cols to %s at %s",
            len(df), len(df.columns), table_name, target_uri,
        )

    # ─── Finalization ─────────────────────────────────────────────────────────

    def finalize(self) -> dict[str, Any]:
        """
        Return the complete lineage metadata for this pipeline run.

        Call this after all to_sql() operations are complete.
        """
        completed_at = datetime.now(timezone.utc)

        # Assign positions to DAG nodes for visualization
        self._layout_dag()

        result = {
            "job": {
                "id": self.job_id,
                "name": self.job_name,
                "integration_id": self.integration_id,
                "started_at": self.started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
            },
            "dataset_lineage": [d.to_dict() for d in self._dataset_lineage],
            "column_lineage": [c.to_dict() for c in self._column_lineage],
            "transformations": [t.to_dict() for t in self._transformations],
            "dag": {
                "nodes": [n.to_dict() for n in self._dag_nodes],
                "edges": [e.to_dict() for e in self._dag_edges],
            },
        }

        logger.info(
            "Lineage finalized: %d datasets, %d columns, %d transforms, %d DAG nodes, %d DAG edges",
            len(self._dataset_lineage),
            len(self._column_lineage),
            len(self._transformations),
            len(self._dag_nodes),
            len(self._dag_edges),
        )

        return result

    def _layout_dag(self) -> None:
        """Assign x/y positions to DAG nodes for visualization."""
        x_spacing = 280
        y_center = 150

        for i, node in enumerate(self._dag_nodes):
            node.metadata["position"] = {"x": i * x_spacing, "y": y_center}

    # ─── Query methods (for impact analysis) ──────────────────────────────────

    def get_column_lineage(self) -> list[dict[str, Any]]:
        """Return all column lineage records."""
        return [c.to_dict() for c in self._column_lineage]

    def get_dataset_lineage(self) -> list[dict[str, Any]]:
        """Return all dataset lineage records."""
        return [d.to_dict() for d in self._dataset_lineage]

    def get_transformations(self) -> list[dict[str, Any]]:
        """Return all transformation steps."""
        return [t.to_dict() for t in self._transformations]

    def get_dag(self) -> dict[str, Any]:
        """Return the DAG (nodes + edges) for visualization."""
        self._layout_dag()
        return {
            "nodes": [n.to_dict() for n in self._dag_nodes],
            "edges": [e.to_dict() for e in self._dag_edges],
        }

    def get_affected_columns(self, source_column: str) -> list[dict[str, Any]]:
        """
        Impact analysis: given a source column name, find all target columns
        that depend on it (directly or through transforms).
        """
        affected = []
        for cl in self._column_lineage:
            if cl.source_column == source_column:
                affected.append({
                    "target_dataset": cl.target_dataset,
                    "target_column": cl.target_column,
                    "transformations": list(cl.transformations),
                    "source_dataset": cl.source_dataset,
                })
        return affected

    def get_affected_datasets(self, source_column: str) -> list[str]:
        """Impact analysis: datasets affected by a source column change."""
        datasets = set()
        for cl in self._column_lineage:
            if cl.source_column == source_column:
                datasets.add(cl.target_dataset)
        return sorted(datasets)

# Copyright (c) 2022, NVIDIA CORPORATION & AFFILIATES.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import pynini
from nemo_text_processing.text_normalization.en.graph_utils import (
    NEMO_NOT_QUOTE,
    NEMO_SIGMA,
    NEMO_SPACE,
    GraphFst,
    delete_preserve_order,
    delete_space,
    delete_extra_space,
)
from nemo_text_processing.text_normalization.it.graph_utils import (
    strip_cardinal_apocope,
)
from nemo_text_processing.text_normalization.it.taggers.date import articles
from pynini.lib import pynutil


class DateFst(GraphFst):
    """
    Finite state transducer for verbalizing date, e.g.
        date { day: "treinta y uno" month: "marzo" year: "dos mil" } -> "treinta y uno de marzo de dos mil"
        date { day: "uno" month: "mayo" year: "del mil novecientos noventa" } -> "primero de mayo del mil novecientos noventa"

    Args:
        deterministic: if True will provide a single transduction option,
            for False multiple transduction are generated (used for audio-based normalization)
    """

    def __init__(self, deterministic: bool = True):
        super().__init__(
            name="date", kind="verbalize", deterministic=deterministic
        )

        day_cardinal = (
            pynutil.delete('day: "')
            + pynini.closure(NEMO_NOT_QUOTE, 1)
            + pynutil.delete('"')
        )
        day = strip_cardinal_apocope(day_cardinal)

        primero = pynini.cdrewrite(
            pynini.cross("uno", "primo"), "[BOS]", "[EOS]", NEMO_SIGMA
        )
        day = (
            (day @ primero)
            if deterministic
            else pynini.union(day, day @ primero)
        )  # Primero for first day is traditional, but will vary depending on region

        month = (
            pynutil.delete("month:")
            + delete_space
            + pynutil.delete('"')
            + pynini.closure(NEMO_NOT_QUOTE, 1)
            + pynutil.delete('"')
        )

        year = (
            pynutil.delete("year:")
            + delete_space
            + pynutil.delete('"')
            + pynini.closure(NEMO_NOT_QUOTE, 1)
            + delete_space
            + pynutil.delete('"')
        )

        # day month year
        graph_dmy = (
            day
            + pynini.closure(delete_extra_space + month, 0, 1)
            + pynini.closure(delete_extra_space + year, 0, 1)
        )

        graph_mdy = (
            month + NEMO_SPACE + day + pynini.closure(NEMO_SPACE + year, 0, 1)
        )
        if deterministic:
            graph_mdy += pynutil.delete(
                " preserve_order: true"
            )  # Only accepts this if was explicitly passed

        self.graph = graph_dmy | graph_mdy
        final_graph = self.graph + delete_preserve_order

        delete_tokens = self.delete_tokens(final_graph)
        self.fst = delete_tokens.optimize()

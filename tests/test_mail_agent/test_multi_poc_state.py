"""
Tests for the multi-POC orchestration state models.

Tests POCStatus, OrchestrationAction, POCRequirement, POCState, POCExecutionPlan,
DataConflict, GlobalValidationResult, OrchestrationDecision, and helper functions.
"""

import pytest

from mail_agent.agent.state import (
    AgentState,
    # Multi-POC models
    POCStatus,
    OrchestrationAction,
    DynamicPOCConfig,
    POCRequirement,
    POCValidationResult,
    POCState,
    POCExecutionPlan,
    DataConflict,
    GlobalValidationResult,
    OrchestrationDecision,
    # Multi-POC helpers
    create_initial_multi_poc_state,
    get_execution_plan,
    get_poc_state,
    update_poc_state,
    get_poc_requirement,
    get_all_poc_states,
    all_pocs_terminal,
    get_ready_pocs,
    get_waiting_pocs,
    get_poc_progress_summary,
    add_poc_to_plan,
)


# ============================================================================
# Multi-POC State Model Tests
# ============================================================================


class TestPOCStatus:
    """Tests for POCStatus enum."""

    def test_status_values(self):
        """Test POCStatus enum values."""
        assert POCStatus.PENDING.value == "pending"
        assert POCStatus.IN_PROGRESS.value == "in_progress"
        assert POCStatus.WAITING.value == "waiting"
        assert POCStatus.COMPLETED.value == "completed"
        assert POCStatus.FAILED.value == "failed"

    def test_status_from_string(self):
        """Test creating POCStatus from string."""
        status = POCStatus("pending")
        assert status == POCStatus.PENDING

        status = POCStatus("completed")
        assert status == POCStatus.COMPLETED


class TestOrchestrationAction:
    """Tests for OrchestrationAction enum."""

    def test_action_values(self):
        """Test OrchestrationAction enum values."""
        assert OrchestrationAction.EXECUTE.value == "execute"
        assert OrchestrationAction.WAIT.value == "wait"
        assert OrchestrationAction.AGGREGATE.value == "aggregate"
        assert OrchestrationAction.FAIL.value == "fail"


class TestDynamicPOCConfig:
    """Tests for DynamicPOCConfig dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        config = DynamicPOCConfig()

        assert config.enabled is False
        assert config.email_source_field is None
        assert config.request_template is None
        assert config.success_criteria_template is None

    def test_enabled_config(self):
        """Test enabled configuration."""
        config = DynamicPOCConfig(
            enabled=True,
            email_source_field="vendor_emails",
            request_template="Request quote from {email}",
            success_criteria_template="Quote received",
        )

        assert config.enabled is True
        assert config.email_source_field == "vendor_emails"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = DynamicPOCConfig(
            enabled=True,
            email_source_field="contacts",
        )

        result = config.to_dict()

        assert result["enabled"] is True
        assert result["email_source_field"] == "contacts"
        assert result["request_template"] is None

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "enabled": True,
            "email_source_field": "emails",
            "request_template": "test",
            "success_criteria_template": "criteria",
        }

        config = DynamicPOCConfig.from_dict(data)

        assert config.enabled is True
        assert config.email_source_field == "emails"


class TestPOCRequirement:
    """Tests for POCRequirement dataclass."""

    def test_basic_requirement(self):
        """Test basic POCRequirement creation."""
        req = POCRequirement(
            id="poc_1",
            email="raj@example.com",
            request="Get 10 recipes",
            success_criteria="10 rows of recipes",
        )

        assert req.id == "poc_1"
        assert req.email == "raj@example.com"
        assert req.dependencies == []
        assert req.execution_order == 1
        assert req.spawns_dynamic_pocs is None

    def test_requirement_with_dependencies(self):
        """Test POCRequirement with dependencies."""
        req = POCRequirement(
            id="poc_2",
            email="priya@example.com",
            request="Validate data from poc_1",
            success_criteria="Validation complete",
            dependencies=["poc_1"],
            execution_order=2,
        )

        assert req.dependencies == ["poc_1"]
        assert req.execution_order == 2

    def test_requirement_with_dynamic_spawn(self):
        """Test POCRequirement with dynamic POC spawning."""
        spawn_config = DynamicPOCConfig(
            enabled=True,
            email_source_field="vendor_list",
        )
        req = POCRequirement(
            id="poc_vendors",
            email="admin@example.com",
            request="Get vendor list",
            success_criteria="List of vendor emails",
            spawns_dynamic_pocs=spawn_config,
        )

        assert req.spawns_dynamic_pocs is not None
        assert req.spawns_dynamic_pocs.enabled is True

    def test_to_dict(self):
        """Test conversion to dictionary."""
        req = POCRequirement(
            id="poc_1",
            email="test@example.com",
            request="Test request",
            success_criteria="Test criteria",
            dependencies=["poc_0"],
        )

        result = req.to_dict()

        assert result["id"] == "poc_1"
        assert result["email"] == "test@example.com"
        assert result["dependencies"] == ["poc_0"]

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "id": "poc_1",
            "email": "test@example.com",
            "request": "Test",
            "success_criteria": "Criteria",
            "dependencies": ["poc_0"],
            "execution_order": 2,
        }

        req = POCRequirement.from_dict(data)

        assert req.id == "poc_1"
        assert req.dependencies == ["poc_0"]
        assert req.execution_order == 2


class TestPOCValidationResult:
    """Tests for POCValidationResult dataclass."""

    def test_valid_result(self):
        """Test valid POCValidationResult."""
        result = POCValidationResult(
            valid=True,
            criteria_met=["10 rows provided", "CSV format"],
            reasoning="All criteria satisfied",
        )

        assert result.valid is True
        assert len(result.criteria_met) == 2
        assert result.should_retry is False
        assert result.should_redirect is False

    def test_invalid_result_needs_retry(self):
        """Test invalid result that needs retry."""
        result = POCValidationResult(
            valid=False,
            criteria_met=["CSV format"],
            criteria_missing=["Only 8 rows instead of 10"],
            should_retry=True,
            reasoning="Missing 2 rows",
        )

        assert result.valid is False
        assert result.should_retry is True
        assert len(result.criteria_missing) == 1

    def test_redirect_result(self):
        """Test redirect validation result."""
        result = POCValidationResult(
            valid=False,
            should_redirect=True,
            redirect_email="other@example.com",
            reasoning="POC suggested contacting other person",
        )

        assert result.valid is False
        assert result.should_redirect is True
        assert result.redirect_email == "other@example.com"

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = POCValidationResult(
            valid=True,
            criteria_met=["criterion1"],
            reasoning="Test reasoning",
        )

        data = original.to_dict()
        restored = POCValidationResult.from_dict(data)

        assert restored.valid == original.valid
        assert restored.criteria_met == original.criteria_met
        assert restored.reasoning == original.reasoning


class TestPOCState:
    """Tests for POCState dataclass."""

    def test_default_state(self):
        """Test default POCState initialization."""
        state = POCState(
            poc_id="poc_1",
            original_email="test@example.com",
        )

        assert state.poc_id == "poc_1"
        assert state.status == POCStatus.PENDING
        assert state.attempts == 0
        assert state.max_attempts == 15
        assert state.conversation is None
        assert state.extracted_data == {}

    def test_state_with_status(self):
        """Test POCState with specific status."""
        state = POCState(
            poc_id="poc_1",
            status=POCStatus.WAITING,
            attempts=2,
            original_email="test@example.com",
        )

        assert state.status == POCStatus.WAITING
        assert state.attempts == 2

    def test_state_with_validation_result(self):
        """Test POCState with validation result."""
        validation = POCValidationResult(
            valid=True,
            reasoning="All good",
        )
        state = POCState(
            poc_id="poc_1",
            original_email="test@example.com",
            validation_result=validation,
        )

        assert state.validation_result is not None
        assert state.validation_result.valid is True

    def test_to_dict(self):
        """Test conversion to dictionary."""
        state = POCState(
            poc_id="poc_1",
            status=POCStatus.COMPLETED,
            attempts=3,
            original_email="test@example.com",
            extracted_data={"key": "value"},
        )

        result = state.to_dict()

        assert result["poc_id"] == "poc_1"
        assert result["status"] == "completed"
        assert result["attempts"] == 3
        assert result["extracted_data"] == {"key": "value"}

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "poc_id": "poc_1",
            "status": "waiting",
            "attempts": 2,
            "max_attempts": 15,
            "original_email": "test@example.com",
            "extracted_data": {},
        }

        state = POCState.from_dict(data)

        assert state.poc_id == "poc_1"
        assert state.status == POCStatus.WAITING
        assert state.attempts == 2


class TestPOCExecutionPlan:
    """Tests for POCExecutionPlan dataclass."""

    def test_basic_plan(self):
        """Test basic POCExecutionPlan creation."""
        plan = POCExecutionPlan(
            global_success_criteria="All data collected",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="test@example.com",
                    request="Get data",
                    success_criteria="Data received",
                )
            ],
            dependency_graph={"poc_1": []},
        )

        assert plan.global_success_criteria == "All data collected"
        assert len(plan.pocs) == 1
        assert plan.dependency_graph["poc_1"] == []

    def test_plan_with_dependencies(self):
        """Test plan with POC dependencies."""
        poc1 = POCRequirement(
            id="poc_1",
            email="first@example.com",
            request="Get list",
            success_criteria="List received",
        )
        poc2 = POCRequirement(
            id="poc_2",
            email="second@example.com",
            request="Process list",
            success_criteria="Processed",
            dependencies=["poc_1"],
        )

        plan = POCExecutionPlan(
            global_success_criteria="All done",
            pocs=[poc1, poc2],
            dependency_graph={
                "poc_1": [],
                "poc_2": ["poc_1"],
            },
        )

        assert plan.dependency_graph["poc_2"] == ["poc_1"]

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = POCExecutionPlan(
            global_success_criteria="Test criteria",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="test@example.com",
                    request="Test",
                    success_criteria="Success",
                )
            ],
            dependency_graph={"poc_1": []},
        )

        data = original.to_dict()
        restored = POCExecutionPlan.from_dict(data)

        assert restored.global_success_criteria == original.global_success_criteria
        assert len(restored.pocs) == len(original.pocs)
        assert restored.pocs[0].id == original.pocs[0].id


class TestDataConflict:
    """Tests for DataConflict dataclass."""

    def test_basic_conflict(self):
        """Test basic DataConflict creation."""
        conflict = DataConflict(
            field_name="price",
            poc_values={"poc_1": "100", "poc_2": "150"},
        )

        assert conflict.field_name == "price"
        assert conflict.poc_values["poc_1"] == "100"
        assert conflict.correct_poc_id is None

    def test_resolved_conflict(self):
        """Test resolved DataConflict."""
        conflict = DataConflict(
            field_name="quantity",
            poc_values={"poc_1": "50", "poc_2": "75"},
            resolution_reasoning="POC 1 is the authoritative source",
            correct_poc_id="poc_1",
            incorrect_poc_ids=["poc_2"],
        )

        assert conflict.correct_poc_id == "poc_1"
        assert "poc_2" in conflict.incorrect_poc_ids

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = DataConflict(
            field_name="test",
            poc_values={"a": "1", "b": "2"},
        )

        data = original.to_dict()
        restored = DataConflict.from_dict(data)

        assert restored.field_name == original.field_name
        assert restored.poc_values == original.poc_values


class TestGlobalValidationResult:
    """Tests for GlobalValidationResult dataclass."""

    def test_valid_result(self):
        """Test valid GlobalValidationResult."""
        result = GlobalValidationResult(
            valid=True,
            all_criteria_met=True,
            reasoning="All data collected successfully",
        )

        assert result.valid is True
        assert result.all_criteria_met is True
        assert result.missing_data == []

    def test_invalid_result(self):
        """Test invalid GlobalValidationResult."""
        result = GlobalValidationResult(
            valid=False,
            all_criteria_met=False,
            missing_data=["vendor pricing", "delivery dates"],
            poc_ids_needing_retry=["poc_2", "poc_3"],
            reasoning="Missing critical information",
        )

        assert result.valid is False
        assert len(result.missing_data) == 2
        assert len(result.poc_ids_needing_retry) == 2


class TestOrchestrationDecision:
    """Tests for OrchestrationDecision dataclass."""

    def test_execute_decision(self):
        """Test execute OrchestrationDecision."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.EXECUTE,
            poc_ids=["poc_1", "poc_2"],
            reason="POCs ready for execution",
        )

        assert decision.action == OrchestrationAction.EXECUTE
        assert len(decision.poc_ids) == 2

    def test_wait_decision(self):
        """Test wait OrchestrationDecision."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.WAIT,
            poc_ids=["poc_1"],
            reason="Waiting for POC reply",
        )

        assert decision.action == OrchestrationAction.WAIT

    def test_aggregate_decision(self):
        """Test aggregate OrchestrationDecision."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.AGGREGATE,
            reason="All POCs completed",
        )

        assert decision.action == OrchestrationAction.AGGREGATE
        assert decision.poc_ids == []

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = OrchestrationDecision(
            action=OrchestrationAction.EXECUTE,
            poc_ids=["poc_1"],
            reason="Test",
        )

        data = original.to_dict()
        restored = OrchestrationDecision.from_dict(data)

        assert restored.action == original.action
        assert restored.poc_ids == original.poc_ids


# ============================================================================
# Multi-POC Helper Function Tests
# ============================================================================


class TestMultiPOCHelpers:
    """Tests for multi-POC helper functions."""

    def test_create_initial_multi_poc_state(self):
        """Test create_initial_multi_poc_state function."""
        instruction = "Contact raj@test.com and priya@test.com for data"

        state = create_initial_multi_poc_state(instruction)

        assert state["user_instruction"] == instruction
        assert state["execution_plan"] is None
        assert state["poc_states"] == {}
        assert state["current_poc_id"] is None
        assert state["aggregated_data"] == {}
        assert state["conflicts"] == []
        assert state["orchestration_phase"] == "planning"

    def test_get_execution_plan_exists(self):
        """Test get_execution_plan with existing plan."""
        plan = POCExecutionPlan(
            global_success_criteria="Test",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="test@test.com",
                    request="Test",
                    success_criteria="Success",
                )
            ],
            dependency_graph={"poc_1": []},
        )

        state: AgentState = {"execution_plan": plan.to_dict()}

        result = get_execution_plan(state)

        assert result.global_success_criteria == "Test"
        assert len(result.pocs) == 1

    def test_get_execution_plan_not_set(self):
        """Test get_execution_plan when not set."""
        state: AgentState = {"execution_plan": None}

        with pytest.raises(ValueError):
            get_execution_plan(state)

    def test_get_poc_state_exists(self):
        """Test get_poc_state with existing state."""
        poc_state = POCState(
            poc_id="poc_1",
            status=POCStatus.WAITING,
            original_email="test@test.com",
        )

        state: AgentState = {
            "poc_states": {"poc_1": poc_state.to_dict()}
        }

        result = get_poc_state(state, "poc_1")

        assert result.poc_id == "poc_1"
        assert result.status == POCStatus.WAITING

    def test_get_poc_state_not_found(self):
        """Test get_poc_state with missing POC."""
        state: AgentState = {"poc_states": {}}

        with pytest.raises(KeyError):
            get_poc_state(state, "nonexistent")

    def test_update_poc_state(self):
        """Test update_poc_state function."""
        poc_state = POCState(
            poc_id="poc_1",
            status=POCStatus.PENDING,
            original_email="test@test.com",
        )

        state: AgentState = {
            "poc_states": {"poc_1": poc_state.to_dict()}
        }

        # Update the state
        poc_state.status = POCStatus.COMPLETED
        poc_state.attempts = 3

        result = update_poc_state(state, "poc_1", poc_state)

        assert result["poc_1"]["status"] == "completed"
        assert result["poc_1"]["attempts"] == 3

    def test_get_poc_requirement(self):
        """Test get_poc_requirement function."""
        plan = POCExecutionPlan(
            global_success_criteria="Test",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="first@test.com",
                    request="First request",
                    success_criteria="First criteria",
                ),
                POCRequirement(
                    id="poc_2",
                    email="second@test.com",
                    request="Second request",
                    success_criteria="Second criteria",
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": []},
        )

        state: AgentState = {"execution_plan": plan.to_dict()}

        result = get_poc_requirement(state, "poc_2")

        assert result.id == "poc_2"
        assert result.email == "second@test.com"

    def test_get_all_poc_states(self):
        """Test get_all_poc_states function."""
        state: AgentState = {
            "poc_states": {
                "poc_1": POCState(
                    poc_id="poc_1",
                    status=POCStatus.COMPLETED,
                    original_email="a@test.com",
                ).to_dict(),
                "poc_2": POCState(
                    poc_id="poc_2",
                    status=POCStatus.WAITING,
                    original_email="b@test.com",
                ).to_dict(),
            }
        }

        result = get_all_poc_states(state)

        assert len(result) == 2
        assert result["poc_1"].status == POCStatus.COMPLETED
        assert result["poc_2"].status == POCStatus.WAITING

    def test_all_pocs_terminal_empty(self):
        """Test all_pocs_terminal with no POCs."""
        state: AgentState = {"poc_states": {}}

        assert all_pocs_terminal(state) is False

    def test_all_pocs_terminal_true(self):
        """Test all_pocs_terminal when all terminal."""
        state: AgentState = {
            "poc_states": {
                "poc_1": {"status": "completed"},
                "poc_2": {"status": "failed"},
            }
        }

        assert all_pocs_terminal(state) is True

    def test_all_pocs_terminal_false(self):
        """Test all_pocs_terminal when some not terminal."""
        state: AgentState = {
            "poc_states": {
                "poc_1": {"status": "completed"},
                "poc_2": {"status": "waiting"},
            }
        }

        assert all_pocs_terminal(state) is False

    def test_get_ready_pocs(self):
        """Test get_ready_pocs function."""
        plan = POCExecutionPlan(
            global_success_criteria="Test",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="Test",
                    success_criteria="Success",
                    dependencies=[],
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="Test",
                    success_criteria="Success",
                    dependencies=["poc_1"],
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": ["poc_1"]},
        )

        state: AgentState = {
            "execution_plan": plan.to_dict(),
            "poc_states": {
                "poc_1": {"status": "pending"},
                "poc_2": {"status": "pending"},
            },
        }

        result = get_ready_pocs(state)

        # Only poc_1 should be ready (no dependencies)
        assert result == ["poc_1"]

    def test_get_ready_pocs_after_completion(self):
        """Test get_ready_pocs after dependency completion."""
        plan = POCExecutionPlan(
            global_success_criteria="Test",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="Test",
                    success_criteria="Success",
                    dependencies=[],
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="Test",
                    success_criteria="Success",
                    dependencies=["poc_1"],
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": ["poc_1"]},
        )

        state: AgentState = {
            "execution_plan": plan.to_dict(),
            "poc_states": {
                "poc_1": {"status": "completed"},
                "poc_2": {"status": "pending"},
            },
        }

        result = get_ready_pocs(state)

        # Now poc_2 should be ready (poc_1 completed)
        assert result == ["poc_2"]

    def test_get_waiting_pocs(self):
        """Test get_waiting_pocs function."""
        state: AgentState = {
            "poc_states": {
                "poc_1": {"status": "completed"},
                "poc_2": {"status": "waiting"},
                "poc_3": {"status": "waiting"},
            }
        }

        result = get_waiting_pocs(state)

        assert len(result) == 2
        assert "poc_2" in result
        assert "poc_3" in result

    def test_get_poc_progress_summary(self):
        """Test get_poc_progress_summary function."""
        state: AgentState = {
            "poc_states": {
                "poc_1": {"status": "completed"},
                "poc_2": {"status": "waiting"},
                "poc_3": {"status": "pending"},
                "poc_4": {"status": "failed"},
                "poc_5": {"status": "in_progress"},
            }
        }

        result = get_poc_progress_summary(state)

        assert result["total"] == 5
        assert result["completed"] == 1
        assert result["waiting"] == 1
        assert result["pending"] == 1
        assert result["failed"] == 1
        assert result["in_progress"] == 1

    def test_add_poc_to_plan(self):
        """Test add_poc_to_plan function."""
        plan = POCExecutionPlan(
            global_success_criteria="Test",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="Test",
                    success_criteria="Success",
                ),
            ],
            dependency_graph={"poc_1": []},
        )

        state: AgentState = {
            "execution_plan": plan.to_dict(),
            "poc_states": {
                "poc_1": {"status": "completed"},
            },
        }

        new_poc = POCRequirement(
            id="poc_2",
            email="b@test.com",
            request="New request",
            success_criteria="New success",
            dependencies=["poc_1"],
        )

        updated_plan, updated_states = add_poc_to_plan(state, new_poc)

        # Check plan was updated
        assert len(updated_plan["pocs"]) == 2
        assert updated_plan["dependency_graph"]["poc_2"] == ["poc_1"]

        # Check state was initialized
        assert "poc_2" in updated_states
        assert updated_states["poc_2"]["status"] == "pending"

from legged_gym.envs.g1.g1_29_config import G129Cfg, G129CfgPPO


class BoosterT1Cfg(G129Cfg):
    class env(G129Cfg.env):
        num_actions = 23
        num_dofs = 23
        num_ballobs = 3
        num_one_step_observations = 6 + num_ballobs + num_dofs * 2 + num_actions
        num_privileged_obs = 6 + num_ballobs + num_dofs * 2 + num_actions + 3 + 1 + 6 + 6 + 1
        num_observations = G129Cfg.env.num_actor_history * num_one_step_observations

    class init_state(G129Cfg.init_state):
        pos = [0.0, 0.0, 0.72]
        default_joint_angles = {
            'AAHead_yaw': 0.0,
            'Head_pitch': 0.0,
            'Left_Shoulder_Pitch': 0.0,
            'Left_Shoulder_Roll': 0.0,
            'Left_Elbow_Pitch': 0.0,
            'Left_Elbow_Yaw': 0.0,
            'Right_Shoulder_Pitch': 0.0,
            'Right_Shoulder_Roll': 0.0,
            'Right_Elbow_Pitch': 0.0,
            'Right_Elbow_Yaw': 0.0,
            'Waist': 0.0,
            'Left_Hip_Pitch': 0.0,
            'Left_Hip_Roll': 0.0,
            'Left_Hip_Yaw': 0.0,
            'Left_Knee_Pitch': 0.0,
            'Left_Ankle_Pitch': 0.0,
            'Left_Ankle_Roll': 0.0,
            'Right_Hip_Pitch': 0.0,
            'Right_Hip_Roll': 0.0,
            'Right_Hip_Yaw': 0.0,
            'Right_Knee_Pitch': 0.0,
            'Right_Ankle_Pitch': 0.0,
            'Right_Ankle_Roll': 0.0,
        }
        init_pos = [0.0] * 23

    class control(G129Cfg.control):
        control_type = 'P'
        stiffness = {
            'Hip_Pitch': 150,
            'Hip_Roll': 150,
            'Hip_Yaw': 150,
            'Knee_Pitch': 300,
            'Ankle_Pitch': 40,
            'Ankle_Roll': 40,
            'Shoulder': 150,
            'Elbow': 150,
            'Waist': 150,
            'Head': 40,
            'AAHead': 40,
        }
        damping = {
            'Hip_Pitch': 5,
            'Hip_Roll': 5,
            'Hip_Yaw': 5,
            'Knee_Pitch': 10,
            'Ankle_Pitch': 1.5,
            'Ankle_Roll': 1.5,
            'Shoulder': 5,
            'Elbow': 5,
            'Waist': 5,
            'Head': 1.5,
            'AAHead': 1.5,
        }
        action_scale = 0.25
        decimation = 4
        curriculum_joints = [
            'Waist',
            'Left_Shoulder_Roll',
            'Right_Shoulder_Roll',
        ]
        left_leg_joints = [
            'Left_Hip_Pitch', 'Left_Hip_Roll', 'Left_Hip_Yaw',
            'Left_Knee_Pitch', 'Left_Ankle_Pitch', 'Left_Ankle_Roll',
        ]
        right_leg_joints = [
            'Right_Hip_Pitch', 'Right_Hip_Roll', 'Right_Hip_Yaw',
            'Right_Knee_Pitch', 'Right_Ankle_Pitch', 'Right_Ankle_Roll',
        ]
        knee_joints = ['Left_Knee_Pitch', 'Right_Knee_Pitch']
        left_arm_joints = [
            'Left_Shoulder_Pitch', 'Left_Shoulder_Roll',
            'Left_Elbow_Pitch', 'Left_Elbow_Yaw',
        ]
        right_arm_joints = [
            'Right_Shoulder_Pitch', 'Right_Shoulder_Roll',
            'Right_Elbow_Pitch', 'Right_Elbow_Yaw',
        ]
        elbow_joints = ['Left_Elbow_Pitch', 'Right_Elbow_Pitch']
        wrist_joints = []

        upper_body_link = "Trunk"
        torso_link = "Trunk"

        left_hip_joints = ['Left_Hip_Pitch', 'Left_Hip_Roll', 'Left_Hip_Yaw']
        right_hip_joints = ['Right_Hip_Pitch', 'Right_Hip_Roll', 'Right_Hip_Yaw']

    class asset(G129Cfg.asset):
        file = '{LEGGED_GYM_ROOT_DIR}/resources/robots/booster_t1/urdf/T1_serial.urdf'
        name = "booster_t1"

        foot_name = "foot_link"
        contact_foot_names = "foot_link"

        hand_name = "hand_link"
        penalize_contacts_on = ["Hip", "Knee", "Shoulder", "Elbow", "Trunk"]
        terminate_after_contacts_on = []

        waist_joints = ["Waist"]
        ankle_joints = ["Left_Ankle_Pitch", "Right_Ankle_Pitch"]
        imu_link = "Trunk"
        knee_names = ["Shank_Left", "Shank_Right"]

        keyframe_name = "keyframe"

    class rewards(G129Cfg.rewards):
        class scales:
            ang_vel_xy = -0.1
            dof_acc = -2.5e-7
            smoothness = -0.1

            torques = -1e-5
            dof_vel = -5e-4

            dof_pos_limits = -3.0
            dof_vel_limits = -2.0
            torque_limits = -3.0

    class dataset(G129Cfg.dataset):
        folder = "{LEGGED_GYM_ROOT_DIR}/resources/datasets/goalkeeper_t1"
        joint_mapping = "{LEGGED_GYM_ROOT_DIR}/resources/datasets/goalkeeper_t1/joint_id.txt"

    class amp(G129Cfg.amp):
        obs_type = 'dof'
        num_obs = 23 * 2


class BoosterT1CfgPPO(G129CfgPPO):
    class runner(G129CfgPPO.runner):
        experiment_name = 'booster_t1'
        run_name = 'booster_t1'
        wandb_project = "goalkeepper"

    amp = BoosterT1Cfg.amp
